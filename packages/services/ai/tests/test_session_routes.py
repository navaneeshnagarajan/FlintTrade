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
    assert (
        client.post(
            "/api/v1/ai/sessions/import",
            json={"surface": "saved-chat", "messages": [{"role": "user", "content": "x"}]},
        ).status_code
        == 503
    )


def test_import_roundtrip(app: Flask) -> None:
    client = app.test_client()
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "conv-42",
            "surface": "saved-chat",
            "title": "Iron condor walkthrough",
            "messages": [
                {"role": "user", "content": "Explain the iron condor payoff.", "timestamp": 1720000000000},
                {"role": "assistant", "content": "Sell an OTM call spread and an OTM put spread."},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"session_id": "conv-42"}

    session = client.get("/api/v1/ai/sessions/conv-42").get_json()["data"]
    assert session["surface"] == "saved-chat"
    assert session["title"] == "Iron condor walkthrough"
    assert [m["role"] for m in session["messages"]] == ["user", "assistant"]
    # timestamp ms → ISO created_at (2024-07-03T09:46:40 UTC).
    assert session["messages"][0]["created_at"] == "2024-07-03T09:46:40+00:00"


def test_import_requires_the_write_guard(app: Flask) -> None:
    def guard() -> Any:
        return jsonify({"status": "error", "message": "operator session required"}), 401

    app.config["BROKER_MGMT_WRITE_GUARD"] = guard
    client = app.test_client()
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={"surface": "saved-chat", "messages": [{"role": "user", "content": "x"}]},
    )
    assert resp.status_code == 401
    # Nothing was written past the guard.
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    assert client.get("/api/v1/ai/sessions").get_json()["data"][0]["id"] == "s1"
    assert len(client.get("/api/v1/ai/sessions").get_json()["data"]) == 1


def test_import_is_idempotent(app: Flask) -> None:
    client = app.test_client()
    payload = {
        "surface": "tutor",
        "messages": [
            {"role": "user", "content": "What is theta decay?"},
            {"role": "assistant", "content": "The daily erosion of option time value."},
        ],
    }
    first = client.post("/api/v1/ai/sessions/import", json=payload)
    second = client.post("/api/v1/ai/sessions/import", json=payload)
    assert first.status_code == second.status_code == 200
    session_id = first.get_json()["data"]["session_id"]
    # No id in the body → deterministic derived id, stable across re-imports.
    assert second.get_json()["data"]["session_id"] == session_id
    session = client.get(f"/api/v1/ai/sessions/{session_id}").get_json()["data"]
    assert len(session["messages"]) == 2


def test_import_id_out_of_bounds_falls_back_to_derived_id(app: Flask) -> None:
    """Unbounded/out-of-alphabet ids never become the sessions primary key.

    Pins finding 10: the explicit id must fullmatch ``[A-Za-z0-9_-]{1,64}``;
    anything else falls back to the deterministic ``imp-`` id (so re-imports
    of the same content stay idempotent regardless of the bad id).
    """
    client = app.test_client()
    messages = [{"role": "user", "content": "What is theta decay?"}]

    def import_with_id(bad_id: str) -> str:
        resp = client.post(
            "/api/v1/ai/sessions/import",
            json={"id": bad_id, "surface": "saved-chat", "messages": messages},
        )
        assert resp.status_code == 200
        return resp.get_json()["data"]["session_id"]

    oversized = "x" * 65
    megabyte = "y" * (1024 * 1024)
    newline = "abc\ndef"
    ids = {import_with_id(bad) for bad in (oversized, megabyte, newline, "sp ace")}
    # Every rejected id collapsed to the SAME derived id for identical content.
    assert len(ids) == 1
    derived = ids.pop()
    assert derived.startswith("imp-")
    # None of the bad ids were stored or echoed back by the list.
    listed = {row["id"] for row in client.get("/api/v1/ai/sessions").get_json()["data"]}
    assert derived in listed
    assert not listed & {oversized, megabyte, newline, "sp ace"}
    # A well-formed 64-char id is still honoured verbatim.
    ok_id = "z" * 64
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={"id": ok_id, "surface": "saved-chat", "messages": messages},
    )
    assert resp.get_json()["data"]["session_id"] == ok_id


def test_import_refuses_id_collision_with_another_surface(app: Flask) -> None:
    """An import naming a live session of a DIFFERENT surface is a 400.

    Pins finding 10: record_exchange upserts by id, so without the check the
    imported messages would silently append into the unrelated conversation.
    """
    client = app.test_client()
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "s1",  # fixture session s1 has surface "advisor"
            "surface": "saved-chat",
            "messages": [{"role": "user", "content": "injected into the advisor session?"}],
        },
    )
    assert resp.status_code == 400
    assert "different surface" in resp.get_json()["message"]
    # The advisor session is untouched.
    session = client.get("/api/v1/ai/sessions/s1").get_json()["data"]
    assert session["surface"] == "advisor"
    assert len(session["messages"]) == 2

    # Same-surface re-import into an existing id remains the idempotent path.
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "s1",
            "surface": "advisor",
            "messages": [{"role": "user", "content": "What is the max pain on BANKNIFTY?"}],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"session_id": "s1"}


def test_import_caps_and_validation(app: Flask) -> None:
    client = app.test_client()

    def post(body: Any) -> int:
        return client.post("/api/v1/ai/sessions/import", json=body).status_code

    ok = {"surface": "saved-chat", "messages": [{"role": "user", "content": "x"}]}
    assert post(ok) == 200
    # Surface allowlist excludes "agent" (and unknowns) for imports.
    assert post({**ok, "surface": "agent"}) == 400
    assert post({**ok, "surface": ""}) == 400
    # messages must be a non-empty list of objects.
    assert post({"surface": "saved-chat"}) == 400
    assert post({"surface": "saved-chat", "messages": []}) == 400
    assert post({"surface": "saved-chat", "messages": "nope"}) == 400
    assert post({"surface": "saved-chat", "messages": ["nope"]}) == 400
    # ≤ 500 messages.
    too_many = [{"role": "user", "content": f"m{i}"} for i in range(501)]
    assert post({"surface": "saved-chat", "messages": too_many}) == 400
    # ≤ 32 KiB per message content.
    big = {"role": "user", "content": "x" * (32 * 1024 + 1)}
    assert post({"surface": "saved-chat", "messages": [big]}) == 400
    # All-skippable messages store nothing and say so.
    assert post({"surface": "saved-chat", "messages": [{"role": "system", "content": "prompt"}]}) == 400
    assert post("not an object") == 400


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
