"""Tests for SecurityMonitor IP tracking and auto-ban.

Run with:
    python -m pytest packages/core/tests/test_security.py -v --import-mode=importlib
"""

from __future__ import annotations

import time


from packages.core.src.security import SecurityMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strict_monitor(**kwargs) -> SecurityMonitor:
    """Return a monitor with low thresholds for fast testing."""
    defaults = {"auth_ban_threshold": 3, "notfound_ban_threshold": 5, "ban_duration": 3600}
    defaults.update(kwargs)
    return SecurityMonitor(**defaults)


# ---------------------------------------------------------------------------
# record_request
# ---------------------------------------------------------------------------


class TestRecordRequest:
    def test_creates_record_on_first_request(self):
        sm = _strict_monitor()
        sm.record_request("1.2.3.4")
        records = sm.get_all_records()
        assert len(records) == 1
        assert records[0].ip == "1.2.3.4"

    def test_increments_request_count(self):
        sm = _strict_monitor()
        sm.record_request("5.5.5.5")
        sm.record_request("5.5.5.5")
        sm.record_request("5.5.5.5")
        records = sm.get_all_records()
        assert records[0].request_count == 3

    def test_updates_last_seen(self):
        sm = _strict_monitor()
        sm.record_request("9.9.9.9")
        before_seen = sm.get_all_records()[0].last_seen
        time.sleep(0.01)
        sm.record_request("9.9.9.9")
        after_seen = sm.get_all_records()[0].last_seen
        assert after_seen > before_seen


# ---------------------------------------------------------------------------
# record_auth_failure / auto-ban
# ---------------------------------------------------------------------------


class TestAuthFailure:
    def test_below_threshold_no_ban(self):
        sm = _strict_monitor(auth_ban_threshold=3)
        sm.record_auth_failure("10.0.0.1")
        sm.record_auth_failure("10.0.0.1")
        assert not sm.is_banned("10.0.0.1")

    def test_at_threshold_auto_bans(self):
        sm = _strict_monitor(auth_ban_threshold=3)
        for _ in range(3):
            sm.record_auth_failure("10.0.0.2")
        assert sm.is_banned("10.0.0.2")

    def test_ban_reason_mentions_threshold(self):
        sm = _strict_monitor(auth_ban_threshold=3)
        for _ in range(3):
            sm.record_auth_failure("10.0.0.3")
        rec = sm.get_banned_ips()[0]
        assert "3" in (rec.ban_reason or "")


# ---------------------------------------------------------------------------
# record_not_found / auto-ban
# ---------------------------------------------------------------------------


class TestNotFound:
    def test_404_flood_triggers_ban(self):
        sm = _strict_monitor(notfound_ban_threshold=5)
        for _ in range(5):
            sm.record_not_found("11.0.0.1")
        assert sm.is_banned("11.0.0.1")

    def test_below_404_threshold_no_ban(self):
        sm = _strict_monitor(notfound_ban_threshold=5)
        for _ in range(4):
            sm.record_not_found("11.0.0.2")
        assert not sm.is_banned("11.0.0.2")


# ---------------------------------------------------------------------------
# Manual ban / unban
# ---------------------------------------------------------------------------


class TestBanUnban:
    def test_manual_ban_sets_is_banned(self):
        sm = _strict_monitor()
        sm.ban_ip("12.0.0.1", "manual test ban")
        assert sm.is_banned("12.0.0.1")

    def test_manual_ban_permanent_when_no_duration(self):
        sm = _strict_monitor()
        sm.ban_ip("12.0.0.2", "permanent ban test")
        rec = sm.get_banned_ips()[0]
        assert rec.ban_expires is None

    def test_manual_ban_with_duration_sets_expiry(self):
        sm = _strict_monitor()
        sm.ban_ip("12.0.0.3", "timed ban", duration=3600)
        rec = sm.get_banned_ips()[0]
        assert rec.ban_expires is not None

    def test_unban_clears_banned_flag(self):
        sm = _strict_monitor()
        sm.ban_ip("13.0.0.1", "to be unbanned")
        sm.unban_ip("13.0.0.1")
        assert not sm.is_banned("13.0.0.1")

    def test_unban_nonexistent_ip_no_error(self):
        sm = _strict_monitor()
        sm.unban_ip("0.0.0.0")  # should not raise


# ---------------------------------------------------------------------------
# Timed ban expiry
# ---------------------------------------------------------------------------


class TestBanExpiry:
    # NOTE: These two tests previously used `time.sleep(1.05)` to wait for the
    # ban window to elapse. The Codex / multi-agent audit on 2026-05-19 flagged
    # the 1-second sleeps as wasted CI wall-time and a flake risk on slow
    # runners. Replaced with a `monkeypatch` over the `time.time` reference in
    # `packages.core.src.security` so the SecurityMonitor sees an artificially
    # advanced clock without any real wait.

    def test_expired_ban_lifted_on_is_banned_call(self, monkeypatch):
        import packages.core.src.security as sec_mod

        clock = {"t": 1_700_000_000.0}
        monkeypatch.setattr(sec_mod.time, "time", lambda: clock["t"])

        sm = _strict_monitor(ban_duration=1)
        sm.ban_ip("20.0.0.1", "short ban", duration=1)
        assert sm.is_banned("20.0.0.1")
        clock["t"] += 1.05  # advance past the 1-second ban window
        assert not sm.is_banned("20.0.0.1")

    def test_expired_ban_absent_from_get_banned(self, monkeypatch):
        import packages.core.src.security as sec_mod

        clock = {"t": 1_700_000_000.0}
        monkeypatch.setattr(sec_mod.time, "time", lambda: clock["t"])

        sm = _strict_monitor()
        sm.ban_ip("20.0.0.2", "expiring", duration=1)
        clock["t"] += 1.05
        bans = sm.get_banned_ips()
        assert all(r.ip != "20.0.0.2" for r in bans)


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_stats_counts_tracked_and_banned(self):
        sm = _strict_monitor(auth_ban_threshold=1)
        sm.record_request("30.0.0.1")
        sm.record_request("30.0.0.2")
        sm.record_auth_failure("30.0.0.2")
        stats = sm.get_stats()
        assert stats["total_ips"] == 2
        assert stats["banned_count"] == 1

    def test_stats_top_offenders_sorted_by_failures(self):
        sm = _strict_monitor(auth_ban_threshold=100)
        sm.record_auth_failure("40.0.0.1")
        for _ in range(5):
            sm.record_auth_failure("40.0.0.2")
        stats = sm.get_stats()
        assert stats["top_offenders"][0]["ip"] == "40.0.0.2"
