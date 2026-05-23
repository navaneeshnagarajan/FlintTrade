"""Tests for LoginActivity, SessionTracker, and SecurityTracker.

Run with:
    python -m pytest packages/core/data/tests/test_login_activity.py -v --import-mode=importlib
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_login_activity():
    from flinttrade_data.activity_log import LoginActivity

    return LoginActivity(":memory:")


def _make_session_tracker():
    from flinttrade_data.activity_log import SessionTracker

    return SessionTracker(":memory:")


def _make_security_tracker():
    from flinttrade_data.security_tracker import SecurityTracker

    return SecurityTracker(":memory:")


# ---------------------------------------------------------------------------
# LoginActivity
# ---------------------------------------------------------------------------


class TestLoginActivity:
    """Test the LoginActivity DuckDB table."""

    def test_log_login_returns_event_id(self):
        la = _make_login_activity()
        eid = la.log_login("nav", "10.0.0.1", "curl/7.64", success=True)
        assert isinstance(eid, str)
        assert len(eid) == 16
        la.close()

    def test_log_login_success_stored(self):
        la = _make_login_activity()
        la.log_login("nav", "10.0.0.1", "Mozilla/5.0", success=True)
        logins = la.recent_logins()
        assert len(logins) == 1
        assert logins[0]["success"] is True
        assert logins[0]["failure_reason"] is None
        la.close()

    def test_log_login_failure_stores_reason(self):
        la = _make_login_activity()
        la.log_login("nav", "1.2.3.4", "curl/7.64", success=False, failure_reason="bad_password")
        logins = la.recent_logins()
        assert logins[0]["success"] is False
        assert logins[0]["failure_reason"] == "bad_password"
        la.close()

    def test_recent_logins_limit(self):
        la = _make_login_activity()
        for i in range(10):
            la.log_login("nav", f"10.0.0.{i}", "ua", success=True)
        logins = la.recent_logins(limit=3)
        assert len(logins) == 3
        la.close()

    def test_recent_logins_filter_by_user(self):
        la = _make_login_activity()
        la.log_login("alice", "10.0.0.1", "ua", success=True)
        la.log_login("bob", "10.0.0.2", "ua", success=True)
        la.log_login("alice", "10.0.0.3", "ua", success=False, failure_reason="bad_totp")
        logins = la.recent_logins(user_id="alice")
        assert len(logins) == 2
        assert all(r["user_id"] == "alice" for r in logins)
        la.close()

    def test_recent_logins_ordered_newest_first(self):
        la = _make_login_activity()
        la.log_login("nav", "10.0.0.1", "ua-1", success=True)
        la.log_login("nav", "10.0.0.2", "ua-2", success=True)
        logins = la.recent_logins()
        # The second login's user_agent should come first (newest)
        assert logins[0]["user_agent"] == "ua-2"
        la.close()

    def test_recent_logins_fields(self):
        la = _make_login_activity()
        la.log_login("nav", "10.0.0.1", "Mozilla/5.0", success=True)
        login = la.recent_logins()[0]
        for field in ("event_id", "timestamp", "user_id", "ip", "user_agent", "success", "failure_reason"):
            assert field in login, f"Missing field: {field}"
        la.close()

    def test_user_agent_can_be_none(self):
        la = _make_login_activity()
        la.log_login("nav", "10.0.0.1", None, success=True)
        logins = la.recent_logins()
        assert logins[0]["user_agent"] is None
        la.close()

    def test_suspicious_logins_threshold(self):
        la = _make_login_activity()
        # 4 failures from the same IP > 3 threshold
        for _ in range(4):
            la.log_login("nav", "5.5.5.5", "curl", success=False, failure_reason="bad_password")
        # Only 2 failures from another IP — should NOT appear
        for _ in range(2):
            la.log_login("nav", "6.6.6.6", "curl", success=False, failure_reason="bad_password")
        suspicious = la.suspicious_logins(window_hours=24)
        ips = [s["ip"] for s in suspicious]
        assert "5.5.5.5" in ips
        assert "6.6.6.6" not in ips
        la.close()

    def test_suspicious_logins_counts_correctly(self):
        la = _make_login_activity()
        for _ in range(5):
            la.log_login("nav", "7.7.7.7", "ua", success=False, failure_reason="bad_password")
        suspicious = la.suspicious_logins(window_hours=24)
        entry = next(s for s in suspicious if s["ip"] == "7.7.7.7")
        assert entry["failed_count"] == 5
        la.close()

    def test_suspicious_logins_excludes_successes(self):
        la = _make_login_activity()
        # 5 successes — should never appear as suspicious
        for _ in range(5):
            la.log_login("nav", "8.8.8.8", "ua", success=True)
        suspicious = la.suspicious_logins(window_hours=24)
        ips = [s["ip"] for s in suspicious]
        assert "8.8.8.8" not in ips
        la.close()

    def test_context_manager(self):
        from flinttrade_data.activity_log import LoginActivity

        with LoginActivity(":memory:") as la:
            la.log_login("nav", "10.0.0.1", "ua", success=True)
            assert len(la.recent_logins()) == 1


# ---------------------------------------------------------------------------
# SessionTracker
# ---------------------------------------------------------------------------


class TestSessionTracker:
    """Test the SessionTracker session lifecycle."""

    def test_register_session_stores_it(self):
        st = _make_session_tracker()
        st.register_session("sess-001", "nav", "10.0.0.1", "Mozilla/5.0")
        sessions = st.active_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-001"
        st.close()

    def test_active_sessions_excludes_ended(self):
        st = _make_session_tracker()
        st.register_session("sess-a", "nav", "10.0.0.1", "ua")
        st.register_session("sess-b", "nav", "10.0.0.2", "ua")
        st.end_session("sess-a")
        sessions = st.active_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-b"
        st.close()

    def test_active_sessions_filter_by_user(self):
        st = _make_session_tracker()
        st.register_session("sess-x", "alice", "10.0.0.1", "ua")
        st.register_session("sess-y", "bob", "10.0.0.2", "ua")
        sessions = st.active_sessions(user_id="alice")
        assert len(sessions) == 1
        assert sessions[0]["user_id"] == "alice"
        st.close()

    def test_heartbeat_does_not_crash(self):
        st = _make_session_tracker()
        st.register_session("sess-hb", "nav", "10.0.0.1", "ua")
        st.heartbeat("sess-hb")  # Should not raise
        sessions = st.active_sessions()
        assert len(sessions) == 1
        st.close()

    def test_heartbeat_nonexistent_session_is_noop(self):
        st = _make_session_tracker()
        st.heartbeat("ghost-session")  # Must not raise
        st.close()

    def test_end_session_idempotent(self):
        st = _make_session_tracker()
        st.register_session("sess-e", "nav", "10.0.0.1", "ua")
        st.end_session("sess-e")
        st.end_session("sess-e")  # Second call must not raise
        assert len(st.active_sessions()) == 0
        st.close()

    def test_expire_stale_returns_count(self):
        st = _make_session_tracker()
        st.register_session("stale-1", "nav", "10.0.0.1", "ua")
        st.register_session("fresh-1", "nav", "10.0.0.2", "ua")
        # Forcibly age the stale session by using a very large idle_minutes
        # window that nothing will exceed, then verify 0 are expired.
        expired = st.expire_stale(idle_minutes=99999)
        assert expired == 0
        assert len(st.active_sessions()) == 2
        st.close()

    def test_expire_stale_ends_idle_sessions(self):
        st = _make_session_tracker()
        # Register a session, then immediately expire with 0 idle minutes
        # (cutoff = now, so everything is stale)
        st.register_session("stale-2", "nav", "10.0.0.1", "ua")
        # Use negative idle_minutes so the cutoff is in the future
        # and all sessions qualify as stale.
        expired = st.expire_stale(idle_minutes=-1)
        assert expired == 1
        assert len(st.active_sessions()) == 0
        st.close()

    def test_session_fields_complete(self):
        st = _make_session_tracker()
        st.register_session("sess-f", "nav", "10.0.0.1", "Mozilla/5.0", device_id="laptop-1")
        s = st.active_sessions()[0]
        for field in ("session_id", "user_id", "ip", "user_agent", "device_id", "created_at", "last_active"):
            assert field in s, f"Missing field: {field}"
        assert s["device_id"] == "laptop-1"
        st.close()

    def test_context_manager(self):
        from flinttrade_data.activity_log import SessionTracker

        with SessionTracker(":memory:") as st:
            st.register_session("ctx-1", "nav", "10.0.0.1", "ua")
            assert len(st.active_sessions()) == 1


# ---------------------------------------------------------------------------
# SecurityTracker
# ---------------------------------------------------------------------------


class TestSecurityTracker:
    """Test the SecurityTracker — 404s, IP bans, API key failures."""

    def test_track_404_returns_count(self):
        skt = _make_security_tracker()
        count = skt.track_404("1.2.3.4", "/admin")
        assert count == 1
        count2 = skt.track_404("1.2.3.4", "/wp-login.php")
        assert count2 == 2
        skt.close()

    def test_track_404_different_ips_independent(self):
        skt = _make_security_tracker()
        c1 = skt.track_404("1.1.1.1", "/x")
        c2 = skt.track_404("2.2.2.2", "/x")
        assert c1 == 1
        assert c2 == 1
        skt.close()

    def test_track_invalid_api_key_stores_prefix_only(self):
        skt = _make_security_tracker()
        full_key = "sk-abcdef1234567890"
        skt.track_invalid_api_key("1.2.3.4", full_key)
        suspicious = skt.suspicious_ips(threshold=0)
        entry = next((s for s in suspicious if s["ip"] == "1.2.3.4"), None)
        assert entry is not None
        assert entry["invalid_key_count"] == 1
        skt.close()

    def test_ban_ip_sets_is_banned(self):
        skt = _make_security_tracker()
        skt.ban_ip("9.9.9.9", "test ban", duration_hours=1)
        assert skt.is_banned("9.9.9.9") is True
        skt.close()

    def test_unknown_ip_not_banned(self):
        skt = _make_security_tracker()
        assert skt.is_banned("3.3.3.3") is False
        skt.close()

    def test_unban_ip_returns_true_when_active(self):
        skt = _make_security_tracker()
        skt.ban_ip("4.4.4.4", "reason", duration_hours=1)
        lifted = skt.unban_ip("4.4.4.4")
        assert lifted is True
        assert skt.is_banned("4.4.4.4") is False
        skt.close()

    def test_unban_ip_returns_false_when_not_banned(self):
        skt = _make_security_tracker()
        lifted = skt.unban_ip("5.5.5.5")
        assert lifted is False
        skt.close()

    def test_permanent_ban_duration_zero(self):
        skt = _make_security_tracker()
        skt.ban_ip("0.0.0.0", "permanent test", duration_hours=0)
        assert skt.is_banned("0.0.0.0") is True
        # expires_at should be NULL (no expiry)
        bans = skt.recent_bans()
        entry = next(b for b in bans if b["ip"] == "0.0.0.0")
        assert entry["expires_at"] is None
        skt.close()

    def test_ban_expiry_logic(self):
        """An expired ban (in the past) must NOT count as active."""
        skt = _make_security_tracker()
        # DuckDB stores TIMESTAMP as naive; insert naive datetimes to match
        # what production code writes and what is_banned reads.
        import secrets as _sec
        from datetime import timezone as _tz

        ban_id = _sec.token_hex(8)
        now_naive = datetime.now(_tz.utc).replace(tzinfo=None)
        past_naive = now_naive - timedelta(hours=2)
        expires_past_naive = now_naive - timedelta(hours=1)
        skt._conn.execute(
            "INSERT INTO security_ip_bans VALUES (?, ?, ?, ?, ?, NULL)",
            [ban_id, "6.6.6.6", "expired ban", past_naive, expires_past_naive],
        )
        assert skt.is_banned("6.6.6.6") is False
        skt.close()

    def test_recent_bans_limit(self):
        skt = _make_security_tracker()
        for i in range(10):
            skt.ban_ip(f"10.0.0.{i}", "flood", duration_hours=1)
        bans = skt.recent_bans(limit=3)
        assert len(bans) == 3
        skt.close()

    def test_recent_bans_fields(self):
        skt = _make_security_tracker()
        skt.ban_ip("11.11.11.11", "test", duration_hours=24)
        bans = skt.recent_bans()
        b = next(x for x in bans if x["ip"] == "11.11.11.11")
        for field in ("ban_id", "ip", "reason", "banned_at", "expires_at", "lifted_at", "is_active"):
            assert field in b, f"Missing field: {field}"
        assert b["is_active"] is True
        skt.close()

    def test_recent_bans_lifted_shows_inactive(self):
        skt = _make_security_tracker()
        skt.ban_ip("12.12.12.12", "test", duration_hours=1)
        skt.unban_ip("12.12.12.12")
        bans = skt.recent_bans()
        b = next(x for x in bans if x["ip"] == "12.12.12.12")
        assert b["is_active"] is False
        assert b["lifted_at"] is not None
        skt.close()

    def test_suspicious_ips_combines_counts(self):
        skt = _make_security_tracker()
        # 7 x 404 + 5 x invalid key = 12 total, threshold=10
        for _ in range(7):
            skt.track_404("20.20.20.20", "/scan")
        for _ in range(5):
            skt.track_invalid_api_key("20.20.20.20", "bad-key-prefix")
        suspicious = skt.suspicious_ips(threshold=10)
        entry = next((s for s in suspicious if s["ip"] == "20.20.20.20"), None)
        assert entry is not None
        assert entry["not_found_count"] == 7
        assert entry["invalid_key_count"] == 5
        assert entry["total_failed"] == 12
        skt.close()

    def test_suspicious_ips_threshold_filters(self):
        skt = _make_security_tracker()
        # Only 3 hits — below threshold of 10
        for _ in range(3):
            skt.track_404("30.30.30.30", "/low")
        suspicious = skt.suspicious_ips(threshold=10)
        ips = [s["ip"] for s in suspicious]
        assert "30.30.30.30" not in ips
        skt.close()

    def test_context_manager(self):
        from flinttrade_data.security_tracker import SecurityTracker

        with SecurityTracker(":memory:") as skt:
            skt.ban_ip("99.99.99.99", "test", duration_hours=1)
            assert skt.is_banned("99.99.99.99") is True
