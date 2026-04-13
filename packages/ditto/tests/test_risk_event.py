"""Tests for RiskEvent and RiskEventLog.

No broker calls — pure data-structure tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))


# ===========================================================================
# RiskEvent
# ===========================================================================


class TestRiskEvent:
    """Structural and serialisation tests for RiskEvent."""

    def _event(self, **overrides):
        from packages.ditto.src.risk_manager import (
            RiskActionTaken,
            RiskEvent,
            RiskEventType,
        )
        defaults = dict(
            event_type=RiskEventType.MAX_LOSS,
            account_id="acc-001",
            threshold_value=-50_000.0,
            current_value=-62_000.0,
            action_taken=RiskActionTaken.CLOSE_ALL,
            exit_order_ids=["OID001", "OID002"],
            notes="daily loss limit breached",
        )
        defaults.update(overrides)
        return RiskEvent(**defaults)

    def test_basic_construction(self):
        event = self._event()
        assert event.event_type == "max_loss"
        assert event.account_id == "acc-001"
        assert event.threshold_value == -50_000.0
        assert event.current_value == -62_000.0
        assert event.action_taken == "close_all"
        assert event.exit_order_ids == ["OID001", "OID002"]
        assert event.notes == "daily loss limit breached"

    def test_timestamp_is_utc_aware_by_default(self):
        event = self._event()
        assert event.timestamp.tzinfo is not None

    def test_to_dict_contains_all_fields(self):
        event = self._event()
        d = event.to_dict()
        assert "timestamp" in d
        assert "event_type" in d
        assert "account_id" in d
        assert "threshold_value" in d
        assert "current_value" in d
        assert "action_taken" in d
        assert "exit_order_ids" in d
        assert "notes" in d

    def test_to_dict_timestamp_is_iso_string(self):
        event = self._event()
        d = event.to_dict()
        # Must be parseable as ISO 8601
        parsed = datetime.fromisoformat(d["timestamp"])  # type: ignore[arg-type]
        assert parsed is not None

    def test_to_dict_exit_order_ids_is_list(self):
        event = self._event()
        d = event.to_dict()
        assert isinstance(d["exit_order_ids"], list)

    def test_str_representation_contains_event_type(self):
        event = self._event()
        s = str(event)
        assert "max_loss" in s
        assert "acc-001" in s

    def test_empty_exit_order_ids_by_default(self):
        from packages.ditto.src.risk_manager import RiskEvent, RiskEventType
        event = RiskEvent(event_type=RiskEventType.KILL_SWITCH)
        assert event.exit_order_ids == []

    def test_different_event_types(self):
        from packages.ditto.src.risk_manager import RiskEvent, RiskEventType
        for etype in RiskEventType:
            ev = RiskEvent(event_type=etype)
            assert ev.event_type == etype.value

    def test_different_action_types(self):
        from packages.ditto.src.risk_manager import (
            RiskActionTaken,
            RiskEvent,
            RiskEventType,
        )
        for action in RiskActionTaken:
            ev = RiskEvent(
                event_type=RiskEventType.MARGIN_BLOCK,
                action_taken=action,
            )
            assert ev.action_taken == action.value

    @pytest.mark.parametrize("threshold,current", [
        (-50_000.0, -60_000.0),
        (0.0, 0.0),
        (100.0, 80.0),
        (-1.0, -0.5),
    ])
    def test_numeric_fields_preserved(self, threshold, current):
        from packages.ditto.src.risk_manager import RiskEvent, RiskEventType
        ev = RiskEvent(
            event_type=RiskEventType.MAX_PROFIT,
            threshold_value=threshold,
            current_value=current,
        )
        assert ev.threshold_value == threshold
        assert ev.current_value == current


# ===========================================================================
# RiskEventLog
# ===========================================================================


class TestRiskEventLog:
    """RiskEventLog append, filter and query operations."""

    def _log(self, max_events: int = 100):
        from packages.ditto.src.risk_manager import RiskEventLog
        return RiskEventLog(max_events=max_events)

    def _event(self, event_type: str = "max_loss", account_id: str = "acc-001"):
        from packages.ditto.src.risk_manager import RiskEvent
        return RiskEvent(event_type=event_type, account_id=account_id)

    def test_empty_log(self):
        log = self._log()
        assert len(log) == 0
        assert log.all() == []

    def test_append_increases_length(self):
        log = self._log()
        log.append(self._event())
        assert len(log) == 1

    def test_all_returns_all_events_in_order(self):
        log = self._log()
        e1 = self._event("max_loss", "acc-001")
        e2 = self._event("kill_switch", "acc-002")
        log.append(e1)
        log.append(e2)
        all_events = log.all()
        assert all_events[0].event_type == "max_loss"
        assert all_events[1].event_type == "kill_switch"

    def test_by_account_filters_correctly(self):
        log = self._log()
        log.append(self._event("max_loss", "acc-001"))
        log.append(self._event("kill_switch", "acc-002"))
        log.append(self._event("margin_block", "acc-001"))
        result = log.by_account("acc-001")
        assert len(result) == 2
        assert all(e.account_id == "acc-001" for e in result)

    def test_by_type_filters_correctly(self):
        log = self._log()
        log.append(self._event("max_loss", "acc-001"))
        log.append(self._event("max_loss", "acc-002"))
        log.append(self._event("kill_switch", "acc-001"))
        result = log.by_type("max_loss")
        assert len(result) == 2
        assert all(e.event_type == "max_loss" for e in result)

    def test_since_filters_by_timestamp(self):
        from packages.ditto.src.risk_manager import RiskEvent, RiskEventType
        log = self._log()
        old = RiskEvent(
            event_type=RiskEventType.MAX_LOSS,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
        recent = RiskEvent(
            event_type=RiskEventType.KILL_SWITCH,
            timestamp=datetime(2026, 4, 1, tzinfo=UTC),
        )
        log.append(old)
        log.append(recent)
        cutoff = datetime(2026, 3, 1, tzinfo=UTC)
        result = log.since(cutoff)
        assert len(result) == 1
        assert result[0].event_type == "kill_switch"

    def test_clear_empties_log(self):
        log = self._log()
        log.append(self._event())
        log.append(self._event())
        log.clear()
        assert len(log) == 0

    def test_max_events_evicts_oldest(self):
        log = self._log(max_events=3)
        for i in range(5):
            from packages.ditto.src.risk_manager import RiskEvent, RiskEventType
            log.append(RiskEvent(
                event_type=RiskEventType.MAX_LOSS,
                account_id=f"acc-{i:03d}",
            ))
        # Only last 3 should remain
        assert len(log) == 3
        remaining_ids = [e.account_id for e in log.all()]
        assert "acc-000" not in remaining_ids
        assert "acc-001" not in remaining_ids
        assert "acc-004" in remaining_ids

    def test_repr_contains_count(self):
        log = self._log()
        log.append(self._event())
        assert "1" in repr(log)

    def test_by_account_empty_list_when_no_match(self):
        log = self._log()
        log.append(self._event("max_loss", "acc-001"))
        result = log.by_account("acc-999")
        assert result == []

    def test_by_type_empty_list_when_no_match(self):
        log = self._log()
        log.append(self._event("max_loss"))
        result = log.by_type("kill_switch")
        assert result == []

    def test_append_logs_warning(self, caplog):
        import logging
        log = self._log()
        with caplog.at_level(logging.WARNING):
            log.append(self._event("max_loss", "acc-test"))
        assert any("RiskEvent" in r.message for r in caplog.records)

    def test_to_dict_round_trip_through_log(self):
        log = self._log()
        from packages.ditto.src.risk_manager import (
            RiskActionTaken,
            RiskEvent,
            RiskEventType,
        )
        event = RiskEvent(
            event_type=RiskEventType.MTM_CIRCUIT,
            account_id="acc-042",
            threshold_value=-50_000.0,
            current_value=-75_000.0,
            action_taken=RiskActionTaken.CLOSE_ALL,
            exit_order_ids=["X1", "X2", "X3"],
            notes="circuit breaker fired",
        )
        log.append(event)
        d = log.all()[0].to_dict()
        assert d["event_type"] == "mtm_circuit"
        assert d["account_id"] == "acc-042"
        assert d["exit_order_ids"] == ["X1", "X2", "X3"]
        assert d["threshold_value"] == -50_000.0
        assert d["current_value"] == -75_000.0


# ===========================================================================
# Integration: RiskManager records events into RiskEventLog
# (optional wiring — tests that RiskEvent fields are well-formed for logging)
# ===========================================================================


class TestRiskEventIntegration:
    """Verify RiskEvent + RiskEventLog work together correctly."""

    def test_manual_event_recording_workflow(self):
        """Simulate the workflow a strategy runner would follow."""
        from packages.ditto.src.risk_manager import (
            RiskActionTaken,
            RiskEvent,
            RiskEventLog,
            RiskEventType,
        )
        log = RiskEventLog()

        # Scenario: daily loss limit hit
        event = RiskEvent(
            event_type=RiskEventType.MAX_LOSS,
            account_id="zerodha-001",
            threshold_value=-50_000.0,
            current_value=-52_000.0,
            action_taken=RiskActionTaken.CLOSE_ALL,
            exit_order_ids=["OA001", "OA002"],
            notes="auto-exit triggered by engine safety layer",
        )
        log.append(event)

        # Scenario: kill switch afterwards
        ks_event = RiskEvent(
            event_type=RiskEventType.KILL_SWITCH,
            account_id="zerodha-001",
            threshold_value=0.0,
            current_value=0.0,
            action_taken=RiskActionTaken.KILL_SWITCH,
        )
        log.append(ks_event)

        assert len(log) == 2
        account_events = log.by_account("zerodha-001")
        assert len(account_events) == 2
        assert account_events[0].event_type == "max_loss"
        assert account_events[1].event_type == "kill_switch"
        # Verify serialisation
        d = account_events[0].to_dict()
        assert d["exit_order_ids"] == ["OA001", "OA002"]
