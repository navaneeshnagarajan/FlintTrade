"""§10.3 security_events / counters / mcp + threshold tests (observability OBS-04)."""

from __future__ import annotations

import pytest

from flinttrade_data.security_tracker import EVENT_TYPES, SecurityTracker, _actor_scopes


@pytest.fixture
def tracker():
    t = SecurityTracker(":memory:")
    try:
        yield t
    finally:
        t.close()


def test_schema_has_section_10_tables(tracker) -> None:
    names = {
        r[0]
        for r in tracker._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"security_events", "security_counters", "mcp_tool_counters"} <= names


def test_actor_scope_resolution() -> None:
    assert _actor_scopes(None, None) == ["global"]
    assert _actor_scopes("u1", None) == ["actor_id:u1"]
    assert _actor_scopes(None, "h1") == ["ip_hash:h1"]
    assert _actor_scopes("u1", "h1") == [
        "ip_hash:h1",
        "actor_id:u1",
        "(actor_id,ip_hash):u1|h1",
    ]


def test_record_event_appends_and_counts(tracker) -> None:
    tracker.record_event(
        "auth.failed_login", actor_id="alice", ip_hash="h1", reason="bad_password"
    )
    events = tracker.recent_events("auth.failed_login")
    assert len(events) == 1
    assert events[0]["actor_id"] == "alice"
    # both-scope event creates three counter rows
    rows = tracker._conn.execute(
        "SELECT actor_scope, count_total FROM security_counters WHERE event_type='auth.failed_login'"
    ).fetchall()
    scopes = {r[0]: r[1] for r in rows}
    assert scopes == {"ip_hash:h1": 1, "actor_id:alice": 1, "(actor_id,ip_hash):alice|h1": 1}


def test_counters_accumulate(tracker) -> None:
    for _ in range(3):
        tracker.record_event("WEBHOOK_REJECTED", ip_hash="h9")
    row = tracker._conn.execute(
        "SELECT count_total FROM security_counters WHERE event_type='WEBHOOK_REJECTED' AND actor_scope='ip_hash:h9'"
    ).fetchone()
    assert row[0] == 3


def test_threshold_crossed_per_scope(tracker) -> None:
    now = 1_000_000.0
    for i in range(5):
        tracker.record_event("auth.failed_login", actor_id="bob", ip_hash="hx", ts=now + i)
    # 5-in-window for actor scope crosses the §10.4 actor threshold (5)
    assert tracker.threshold_crossed(
        "auth.failed_login", actor_id="bob", limit=5, window_seconds=300, now=now + 5
    ) is True
    # a different, quiet actor is unaffected (per-scope evaluation)
    assert tracker.threshold_crossed(
        "auth.failed_login", actor_id="carol", limit=5, window_seconds=300, now=now + 5
    ) is False


def test_threshold_respects_window(tracker) -> None:
    now = 2_000_000.0
    tracker.record_event("auth.failed_login", ip_hash="old", ts=now - 1000)  # outside 300s
    tracker.record_event("auth.failed_login", ip_hash="old", ts=now - 10)    # inside
    assert tracker.count_events_in_window(
        "auth.failed_login", ip_hash="old", window_seconds=300, now=now
    ) == 1


def test_mcp_tool_decision_counters(tracker) -> None:
    tracker.mcp_tool_decision("trade.place_order", "denied")
    tracker.mcp_tool_decision("trade.place_order", "denied")
    tracker.mcp_tool_decision("trade.place_order", "external_input_refused")
    tracker.mcp_tool_decision("data.quote", "bogus")  # coerced to 'other'
    rows = {
        (r[0], r[1]): r[2]
        for r in tracker._conn.execute(
            "SELECT tool_name, decision, count_total FROM mcp_tool_counters"
        ).fetchall()
    }
    assert rows[("trade.place_order", "denied")] == 2
    assert rows[("trade.place_order", "external_input_refused")] == 1
    assert rows[("data.quote", "other")] == 1


def test_event_taxonomy_present() -> None:
    assert "WEBHOOK_REPLAY_REJECTED" in EVENT_TYPES
    assert "BROKER_SDK_ATTEST_FAIL" in EVENT_TYPES
    assert "auth.failed_login" in EVENT_TYPES
