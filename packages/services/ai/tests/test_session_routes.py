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
    (The one carve-out — saved-chat promotion of a live advisor/tutor capture
    — is pinned separately below.)
    """
    client = app.test_client()
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "s1",  # fixture session s1 has surface "advisor"
            "surface": "tutor",
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


def test_share_import_promotes_a_live_advisor_session(app: Flask) -> None:
    """The Share flow works on a live-captured advisor conversation.

    Pins the finding-10 over-refusal fix: AIAdvisorWidget captures the
    conversation under its id with surface "advisor", and Share then imports
    the SAME id with surface "saved-chat" — that must succeed (it is the same
    operator saving the same conversation), append idempotently, and leave
    the stored surface unchanged (reads serve the share link by id anyway).
    """
    client = app.test_client()
    share_payload = {
        "id": "s1",  # fixture session s1: live advisor capture
        "surface": "saved-chat",
        "messages": [
            {"role": "user", "content": "What is the max pain on BANKNIFTY?"},
            {"role": "assistant", "content": "Near 51000 for this expiry."},
        ],
    }
    resp = client.post("/api/v1/ai/sessions/import", json=share_payload)
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"session_id": "s1"}

    # Idempotent: the content-hash message ids dedupe the re-imported history.
    session = client.get("/api/v1/ai/sessions/s1").get_json()["data"]
    assert session["surface"] == "advisor"  # stored surface stays unchanged
    assert len(session["messages"]) == 2

    # Sharing again after the conversation grew appends only the new message.
    share_payload["messages"].append({"role": "user", "content": "And for NIFTY?"})
    assert client.post("/api/v1/ai/sessions/import", json=share_payload).status_code == 200
    session = client.get("/api/v1/ai/sessions/s1").get_json()["data"]
    assert [m["content"] for m in session["messages"]][-1] == "And for NIFTY?"
    assert len(session["messages"]) == 3


def test_share_import_promotes_a_live_tutor_session(app: Flask) -> None:
    """tutor → saved-chat promotion succeeds likewise (AITutorPill capture)."""
    store: AiSessionStore = app.config["AI_SESSION_STORE"]
    store.record_exchange(
        "t1",
        "tutor",
        [
            {"role": "user", "content": "What is a strangle?"},
            {"role": "assistant", "content": "An OTM call plus an OTM put."},
        ],
    )
    client = app.test_client()
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "t1",
            "surface": "saved-chat",
            "messages": [
                {"role": "user", "content": "What is a strangle?"},
                {"role": "assistant", "content": "An OTM call plus an OTM put."},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"session_id": "t1"}
    session = client.get("/api/v1/ai/sessions/t1").get_json()["data"]
    assert session["surface"] == "tutor"
    assert len(session["messages"]) == 2


def test_saved_chat_promotion_is_the_only_cross_surface_import(app: Flask) -> None:
    """Every cross-surface pair other than advisor/tutor → saved-chat still 400s."""
    store: AiSessionStore = app.config["AI_SESSION_STORE"]
    store.record_exchange("a1", "agent", [{"role": "user", "content": "run the scan"}])
    store.record_exchange("c1", "saved-chat", [{"role": "user", "content": "old share"}])
    client = app.test_client()

    def import_as(session_id: str, surface: str) -> int:
        return client.post(
            "/api/v1/ai/sessions/import",
            json={
                "id": session_id,
                "surface": surface,
                "messages": [{"role": "user", "content": "cross-surface attempt"}],
            },
        ).status_code

    assert import_as("s1", "tutor") == 400  # advisor id imported as tutor
    assert import_as("a1", "saved-chat") == 400  # agent sessions are never promotable
    assert import_as("c1", "advisor") == 400  # no demotion out of saved-chat
    assert import_as("c1", "tutor") == 400


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


def test_import_explicit_message_ids_keep_identical_contents(app: Flask) -> None:
    """Byte-identical same-role contents survive when each carries its own id.

    Pins the chunked-import silent-loss defect: the client splits an
    over-32-KiB message into fixed-budget chunks, and uniformly repetitive
    content (e.g. "य" repeats — 3 UTF-8 bytes per character) packs into
    byte-identical chunks. Without explicit ids the store's content-hash
    fallback collapses them via INSERT OR IGNORE, permanently losing content
    once the client-side copy is gone.
    """
    client = app.test_client()
    chunk = "य" * 100
    payload = {
        "id": "conv-chunks",
        "surface": "saved-chat",
        "messages": [
            {"id": "m0-c0", "role": "user", "content": chunk, "timestamp": 1720000000000},
            {"id": "m0-c1", "role": "user", "content": chunk, "timestamp": 1720000000000},
            {"id": "m0-c2", "role": "user", "content": "tail", "timestamp": 1720000000000},
        ],
    }
    assert client.post("/api/v1/ai/sessions/import", json=payload).status_code == 200
    session = client.get("/api/v1/ai/sessions/conv-chunks").get_json()["data"]
    assert [m["content"] for m in session["messages"]] == [chunk, chunk, "tail"]
    # The stored id is the client id namespaced by the session.
    assert session["messages"][0]["id"] == "imp:conv-chunks:m0-c0"
    # Re-import (a retry after a mid-batch failure) is an idempotent no-op.
    assert client.post("/api/v1/ai/sessions/import", json=payload).status_code == 200
    session = client.get("/api/v1/ai/sessions/conv-chunks").get_json()["data"]
    assert [m["content"] for m in session["messages"]] == [chunk, chunk, "tail"]


@pytest.mark.parametrize(
    ("char", "repeats"),
    [
        ("य", 33_100),  # 3-byte char: three byte-identical full chunks (the defect case)
        ("é", 20_000),  # 2-byte char across the 32 KiB boundary
        ("🚀", 9_000),  # 4-byte emoji across the boundary
    ],
)
def test_import_chunked_boundary_reassembly(app: Flask, char: str, repeats: int) -> None:
    """A multi-byte repeat crossing the 32 KiB cap reassembles exactly.

    Mirrors what the fixed client sends: fixed-budget chunks (each within the
    cap) with deterministic per-chunk ids and one shared timestamp. The
    recorded messages, joined in stored order, must reproduce the original —
    and a re-import must change nothing.
    """
    client = app.test_client()
    content = char * repeats
    per_chunk = (32 * 1024) // len(char.encode("utf-8"))
    chunks = [content[i : i + per_chunk] for i in range(0, repeats, per_chunk)]
    assert len(chunks) > 1
    assert all(len(piece.encode("utf-8")) <= 32 * 1024 for piece in chunks)
    payload = {
        "id": "conv-exact",
        "surface": "saved-chat",
        "messages": [
            {"id": f"m0-c{index}", "role": "user", "content": piece, "timestamp": 1720000000000}
            for index, piece in enumerate(chunks)
        ],
    }
    assert client.post("/api/v1/ai/sessions/import", json=payload).status_code == 200
    session = client.get("/api/v1/ai/sessions/conv-exact").get_json()["data"]
    recorded = [m["content"] for m in session["messages"]]
    assert "".join(recorded) == content
    assert len(recorded) == len(chunks)
    # Idempotent re-import: nothing duplicated, nothing lost.
    assert client.post("/api/v1/ai/sessions/import", json=payload).status_code == 200
    session = client.get("/api/v1/ai/sessions/conv-exact").get_json()["data"]
    assert [m["content"] for m in session["messages"]] == recorded


def test_import_message_id_validation_and_namespacing(app: Flask) -> None:
    """Out-of-shape message ids fall back to the content hash; accepted ids
    are namespaced per session so equal client ids never collide globally."""
    client = app.test_client()

    # Invalid ids (non-string, oversized, out-of-alphabet) are ignored, so
    # byte-identical contents collapse to one row — the documented fallback.
    resp = client.post(
        "/api/v1/ai/sessions/import",
        json={
            "id": "conv-badids",
            "surface": "saved-chat",
            "messages": [
                {"id": 42, "role": "user", "content": "same text"},
                {"id": "x" * 129, "role": "user", "content": "same text"},
                {"id": "sp ace", "role": "user", "content": "same text"},
                {"id": "new\nline", "role": "user", "content": "same text"},
            ],
        },
    )
    assert resp.status_code == 200
    session = client.get("/api/v1/ai/sessions/conv-badids").get_json()["data"]
    assert len(session["messages"]) == 1
    assert session["messages"][0]["id"].startswith("h-")

    # The SAME message id in two different sessions stores both messages —
    # the messages table's id is a global primary key, so an unscoped client
    # id would silently drop the second session's message.
    for conv, text in (("conv-ns-a", "alpha"), ("conv-ns-b", "beta")):
        resp = client.post(
            "/api/v1/ai/sessions/import",
            json={
                "id": conv,
                "surface": "saved-chat",
                "messages": [{"id": "m0-c0", "role": "user", "content": text}],
            },
        )
        assert resp.status_code == 200
    session_a = client.get("/api/v1/ai/sessions/conv-ns-a").get_json()["data"]
    session_b = client.get("/api/v1/ai/sessions/conv-ns-b").get_json()["data"]
    assert [m["content"] for m in session_a["messages"]] == ["alpha"]
    assert [m["content"] for m in session_b["messages"]] == ["beta"]


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
