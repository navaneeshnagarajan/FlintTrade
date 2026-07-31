"""Tests for the AI session store (AI2 — SQLite + FTS5 cross-session recall)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from flinttrade_ai.session_store import AiSessionStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store() -> AiSessionStore:
    return AiSessionStore(":memory:")


def _exchange(store: AiSessionStore, session_id: str = "s1") -> int:
    return store.record_exchange(
        session_id,
        "advisor",
        [
            {"role": "user", "content": "What is the max pain on BANKNIFTY today?"},
            {"role": "assistant", "content": "Max pain sits near 51000 for this expiry."},
        ],
    )


def test_record_and_read_roundtrip(store: AiSessionStore) -> None:
    inserted = _exchange(store)
    assert inserted == 2

    sessions = store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["surface"] == "advisor"
    assert sessions[0]["message_count"] == 2
    assert "max pain" in sessions[0]["title"].lower()

    session = store.get_session("s1")
    assert session is not None
    assert [m["role"] for m in session["messages"]] == ["user", "assistant"]


def test_replaying_the_full_history_is_idempotent(store: AiSessionStore) -> None:
    _exchange(store)
    # The advisor sends the FULL history each request — replay must insert 0.
    assert _exchange(store) == 0
    session = store.get_session("s1")
    assert session is not None
    assert len(session["messages"]) == 2


def test_legacy_content_ids_are_rekeyed_on_open(tmp_path: Path) -> None:
    """A store written before the SHA-256 switch stays replay-idempotent.

    The migration recomputes every ``h-`` id from the columns that produced
    it, so it does not care what the old digest was — the stand-in ids below
    play the part of the pre-SHA-256 ones.
    """
    db = tmp_path / "ai_sessions.sqlite"
    store = AiSessionStore(db)
    _exchange(store)
    store.close()

    conn = sqlite3.connect(db)
    for index, (rowid,) in enumerate(conn.execute("SELECT rowid FROM messages").fetchall()):
        conn.execute(
            "UPDATE messages SET id = ? WHERE rowid = ?", (f"h-legacy{index:014d}", rowid)
        )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    upgraded = AiSessionStore(db)
    try:
        # Replaying the same history must still insert nothing — no duplicates.
        assert _exchange(upgraded) == 0
        session = upgraded.get_session("s1")
        assert session is not None
        assert len(session["messages"]) == 2
        assert all(not m["id"].startswith("h-legacy") for m in session["messages"])
        # Search still resolves through the FTS mirror after the re-key.
        assert upgraded.search("banknifty")[0]["session_id"] == "s1"
    finally:
        upgraded.close()

    # Re-opening does not re-run the migration.
    reopened = AiSessionStore(db)
    try:
        assert reopened.get_session("s1") is not None
    finally:
        reopened.close()


def test_fts_search_hits_message_content(store: AiSessionStore) -> None:
    _exchange(store)
    store.record_exchange(
        "s2",
        "advisor",
        [{"role": "user", "content": "Explain the iron condor payoff."}],
    )

    hits = store.search("banknifty")
    assert len(hits) >= 1
    assert all(h["session_id"] == "s1" for h in hits)
    assert "snippet" in hits[0]

    assert store.search("condor")[0]["session_id"] == "s2"
    # Malformed FTS syntax must not raise.
    assert store.search('"unbalanced AND (') == []
    assert store.search("") == []


def test_delete_and_prune(store: AiSessionStore) -> None:
    for i in range(5):
        store.record_exchange(
            f"s{i}", "advisor", [{"role": "user", "content": f"question {i}"}]
        )
    assert store.delete_session("s0") is True
    assert store.delete_session("s0") is False
    assert store.prune(max_sessions=2) == 2
    assert len(store.list_sessions()) == 2
    # FTS rows for deleted sessions are gone too (trigger-synced).
    assert store.search("question") != []
    assert all(h["session_id"] in {"s3", "s4"} for h in store.search("question"))


def test_session_surface_probe(store: AiSessionStore) -> None:
    """session_surface answers without loading messages; unknown ids are None."""
    _exchange(store)
    assert store.session_surface("s1") == "advisor"
    assert store.session_surface("never-recorded") is None


def test_invalid_inputs_fail_closed(store: AiSessionStore) -> None:
    with pytest.raises(ValueError):
        store.record_exchange("", "advisor", [{"role": "user", "content": "x"}])
    with pytest.raises(ValueError):
        store.record_exchange("s1", "not-a-surface", [{"role": "user", "content": "x"}])
    # System/blank messages are skipped, not stored.
    assert store.record_exchange(
        "s1", "advisor", [{"role": "system", "content": "prompt"}, {"role": "user", "content": " "}]
    ) == 0
