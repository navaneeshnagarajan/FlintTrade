"""Tests for AlertTriggerLog — DuckDB-backed alert trigger audit trail.

All tests use in-memory DuckDB (db_path=":memory:") for full isolation.
No real timestamps are mocked — the tests use time.sleep-free assertions
that tolerate any reasonable trigger_epoch value.
"""

from __future__ import annotations

import time

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def log():
    """Fresh in-memory AlertTriggerLog for each test."""
    from flinttrade_webhooks.alert_trigger_log import AlertTriggerLog
    return AlertTriggerLog(db_path=":memory:")


# ---------------------------------------------------------------------------
# TriggerEvent dataclass
# ---------------------------------------------------------------------------


class TestTriggerEvent:
    def test_fields_set_correctly(self):
        from flinttrade_webhooks.alert_trigger_log import TriggerEvent
        te = TriggerEvent(
            trigger_id="tid-001",
            alert_id="alert-001",
            symbol="NIFTY",
            condition="PRICE_CROSS_ABOVE",
            alert_price=24500.0,
            trigger_price=24502.5,
            triggered_at="2026-04-08T15:30:00+05:30",
        )
        assert te.trigger_id == "tid-001"
        assert te.symbol == "NIFTY"
        assert te.condition == "PRICE_CROSS_ABOVE"
        assert te.alert_price == pytest.approx(24500.0)
        assert te.trigger_price == pytest.approx(24502.5)

    def test_triggered_epoch_defaults_to_current_time(self):
        from flinttrade_webhooks.alert_trigger_log import TriggerEvent
        before = time.time()
        te = TriggerEvent(
            trigger_id="x",
            alert_id="a",
            symbol="NIFTY",
            condition="ABOVE",
            alert_price=100.0,
            trigger_price=101.0,
            triggered_at="2026-04-08T09:15:00+05:30",
        )
        after = time.time()
        assert before <= te.triggered_epoch <= after


# ---------------------------------------------------------------------------
# log_trigger
# ---------------------------------------------------------------------------


class TestLogTrigger:
    def test_returns_non_empty_trigger_id(self, log):
        tid = log.log_trigger(
            alert_id="alert-001",
            trigger_price=24502.5,
            alert_price=24500.0,
            symbol="NIFTY",
            condition="PRICE_CROSS_ABOVE",
        )
        assert isinstance(tid, str)
        assert len(tid) > 0

    def test_trigger_ids_are_unique(self, log):
        tid1 = log.log_trigger(
            alert_id="a1", trigger_price=100.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        tid2 = log.log_trigger(
            alert_id="a1", trigger_price=101.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        assert tid1 != tid2

    def test_multiple_triggers_persist(self, log):
        for i in range(5):
            log.log_trigger(
                alert_id=f"alert-{i}",
                trigger_price=float(24500 + i),
                alert_price=24500.0,
                symbol="BANKNIFTY",
                condition="PRICE_CROSS_BELOW",
            )
        triggers = log.get_triggers(limit=10)
        assert len(triggers) == 5


# ---------------------------------------------------------------------------
# get_triggers
# ---------------------------------------------------------------------------


class TestGetTriggers:
    def test_returns_trigger_events(self, log):
        from flinttrade_webhooks.alert_trigger_log import TriggerEvent
        log.log_trigger(
            alert_id="alert-A", trigger_price=200.0, alert_price=200.0,
            symbol="SENSEX", condition="ABOVE",
        )
        triggers = log.get_triggers()
        assert len(triggers) == 1
        assert isinstance(triggers[0], TriggerEvent)

    def test_filter_by_alert_id(self, log):
        log.log_trigger(
            alert_id="alert-A", trigger_price=100.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        log.log_trigger(
            alert_id="alert-B", trigger_price=200.0, alert_price=200.0,
            symbol="NIFTY", condition="BELOW",
        )
        triggers_a = log.get_triggers(alert_id="alert-A")
        assert len(triggers_a) == 1
        assert triggers_a[0].alert_id == "alert-A"

    def test_limit_respected(self, log):
        for i in range(10):
            log.log_trigger(
                alert_id="alert-X", trigger_price=float(i),
                alert_price=0.0, symbol="X", condition="ABOVE",
            )
        triggers = log.get_triggers(limit=5)
        assert len(triggers) == 5

    def test_empty_log_returns_empty_list(self, log):
        assert log.get_triggers() == []

    def test_trigger_fields_round_trip(self, log):
        log.log_trigger(
            alert_id="alert-RT",
            trigger_price=24512.75,
            alert_price=24500.0,
            symbol="NIFTY",
            condition="PRICE_CROSS_ABOVE",
        )
        triggers = log.get_triggers(alert_id="alert-RT")
        te = triggers[0]
        assert te.alert_id == "alert-RT"
        assert te.symbol == "NIFTY"
        assert te.condition == "PRICE_CROSS_ABOVE"
        assert te.trigger_price == pytest.approx(24512.75)
        assert te.alert_price == pytest.approx(24500.0)
        assert te.triggered_at != ""
        assert te.trigger_id != ""


# ---------------------------------------------------------------------------
# should_debounce
# ---------------------------------------------------------------------------


class TestShouldDebounce:
    def test_no_prior_trigger_does_not_debounce(self, log):
        assert log.should_debounce("never-triggered-alert", cooldown_sec=60) is False

    def test_recent_trigger_debounces(self, log):
        log.log_trigger(
            alert_id="alert-D", trigger_price=100.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        assert log.should_debounce("alert-D", cooldown_sec=60) is True

    def test_zero_cooldown_does_not_debounce(self, log):
        log.log_trigger(
            alert_id="alert-Z", trigger_price=100.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        # cooldown_sec=0 means no cooldown — should never debounce
        assert log.should_debounce("alert-Z", cooldown_sec=0) is False

    def test_different_alert_ids_are_independent(self, log):
        log.log_trigger(
            alert_id="alert-1", trigger_price=100.0, alert_price=100.0,
            symbol="NIFTY", condition="ABOVE",
        )
        # alert-2 has never triggered — should not be debounced
        assert log.should_debounce("alert-2", cooldown_sec=60) is False


# ---------------------------------------------------------------------------
# auto_pause_alert / is_paused / resume_alert
# ---------------------------------------------------------------------------


class TestAutoPause:
    def test_alert_not_paused_initially(self, log):
        assert log.is_paused("alert-P") is False

    def test_auto_pause_marks_alert_paused(self, log):
        log.auto_pause_alert("alert-P")
        assert log.is_paused("alert-P") is True

    def test_auto_pause_idempotent(self, log):
        log.auto_pause_alert("alert-Q")
        log.auto_pause_alert("alert-Q")  # second call should not raise
        assert log.is_paused("alert-Q") is True

    def test_resume_clears_paused_flag(self, log):
        log.auto_pause_alert("alert-R")
        assert log.is_paused("alert-R") is True
        log.resume_alert("alert-R")
        assert log.is_paused("alert-R") is False

    def test_resume_non_paused_alert_is_safe(self, log):
        log.resume_alert("never-paused")  # must not raise
        assert log.is_paused("never-paused") is False

    def test_pause_does_not_affect_triggers_table(self, log):
        """Pausing an alert must not remove its trigger history."""
        log.log_trigger(
            alert_id="alert-S", trigger_price=99.0, alert_price=99.0,
            symbol="SENSEX", condition="ABOVE",
        )
        log.auto_pause_alert("alert-S")
        triggers = log.get_triggers(alert_id="alert-S")
        assert len(triggers) == 1

    def test_different_alerts_pause_independently(self, log):
        log.auto_pause_alert("alert-X")
        assert log.is_paused("alert-X") is True
        assert log.is_paused("alert-Y") is False
