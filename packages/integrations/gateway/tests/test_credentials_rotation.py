"""Tests for packages/integrations/gateway/src/credentials_rotation.py.

Covers: scheduling, immediate rotation, status queries, error handling.

Run with:
    python -m pytest packages/integrations/gateway/tests/test_credentials_rotation.py -v --import-mode=importlib
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from flinttrade_gateway.credentials_rotation import (
    CredentialsRotator,
    RotationResult,
)

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_scheduler() -> MagicMock:
    """Mock APScheduler BackgroundScheduler."""
    sched = MagicMock()
    sched.running = True
    return sched


@pytest.fixture
def mock_manager() -> MagicMock:
    """Mock credentials manager with refresh_token support."""
    return MagicMock()


@pytest.fixture
def rotator(mock_manager: MagicMock, mock_scheduler: MagicMock) -> CredentialsRotator:
    return CredentialsRotator(
        credentials_manager=mock_manager,
        scheduler=mock_scheduler,
    )


# ---------------------------------------------------------------------------
# RotationResult dataclass
# ---------------------------------------------------------------------------


class TestRotationResult:
    def test_success_defaults(self) -> None:
        result = RotationResult(broker="zerodha", success=True)
        assert result.broker == "zerodha"
        assert result.success is True
        assert result.error is None
        assert result.rotation_type == "refresh"
        assert isinstance(result.rotated_at, datetime)

    def test_failure_stores_error(self) -> None:
        result = RotationResult(broker="angel", success=False, error="Token expired")
        assert result.success is False
        assert result.error == "Token expired"


# ---------------------------------------------------------------------------
# schedule_daily_refresh
# ---------------------------------------------------------------------------


class TestScheduleDailyRefresh:
    def test_registers_cron_job(
        self, rotator: CredentialsRotator, mock_scheduler: MagicMock
    ) -> None:
        rotator.schedule_daily_refresh("zerodha", time_ist="08:05")
        mock_scheduler.add_job.assert_called_once()
        kwargs = mock_scheduler.add_job.call_args
        assert kwargs[1]["trigger"] == "cron"
        assert kwargs[1]["hour"] == 8
        assert kwargs[1]["minute"] == 5

    def test_job_id_contains_broker_name(
        self, rotator: CredentialsRotator, mock_scheduler: MagicMock
    ) -> None:
        rotator.schedule_daily_refresh("zerodha")
        kwargs = mock_scheduler.add_job.call_args[1]
        assert "zerodha" in kwargs["id"]

    def test_replaces_existing_job(
        self, rotator: CredentialsRotator, mock_scheduler: MagicMock
    ) -> None:
        rotator.schedule_daily_refresh("zerodha", "08:00")
        rotator.schedule_daily_refresh("zerodha", "09:00")
        # Both calls should have replace_existing=True.
        for c in mock_scheduler.add_job.call_args_list:
            assert c[1].get("replace_existing") is True

    def test_invalid_time_raises(self, rotator: CredentialsRotator) -> None:
        with pytest.raises(ValueError):
            rotator.schedule_daily_refresh("zerodha", time_ist="25:00")

    def test_malformed_time_raises(self, rotator: CredentialsRotator) -> None:
        with pytest.raises(ValueError):
            rotator.schedule_daily_refresh("zerodha", time_ist="8am")


# ---------------------------------------------------------------------------
# schedule_weekly_rotation
# ---------------------------------------------------------------------------


class TestScheduleWeeklyRotation:
    def test_registers_weekly_cron(
        self, rotator: CredentialsRotator, mock_scheduler: MagicMock
    ) -> None:
        rotator.schedule_weekly_rotation("angel", day=0, time_ist="07:30")
        mock_scheduler.add_job.assert_called_once()
        kwargs = mock_scheduler.add_job.call_args[1]
        assert kwargs["trigger"] == "cron"
        assert kwargs["day_of_week"] == 0

    def test_invalid_day_raises(self, rotator: CredentialsRotator) -> None:
        with pytest.raises(ValueError, match="day"):
            rotator.schedule_weekly_rotation("angel", day=7, time_ist="08:00")


# ---------------------------------------------------------------------------
# rotate_now
# ---------------------------------------------------------------------------


class TestRotateNow:
    def test_rotate_now_returns_result(self, rotator: CredentialsRotator) -> None:
        result = rotator.rotate_now("zerodha")
        assert isinstance(result, RotationResult)
        assert result.broker == "zerodha"

    def test_rotate_now_success_when_no_refresh_hook(
        self, rotator: CredentialsRotator, mock_manager: MagicMock
    ) -> None:
        # Manager without refresh_token attribute.
        del mock_manager.refresh_token
        result = rotator.rotate_now("zerodha")
        assert result.success is True

    def test_rotate_now_calls_refresh_token_if_available(
        self, rotator: CredentialsRotator, mock_manager: MagicMock
    ) -> None:
        rotator.rotate_now("zerodha")
        mock_manager.refresh_token.assert_called_once_with("zerodha")

    def test_rotate_now_failure_on_exception(
        self, rotator: CredentialsRotator, mock_manager: MagicMock
    ) -> None:
        mock_manager.refresh_token.side_effect = RuntimeError("Network error")
        result = rotator.rotate_now("zerodha")
        assert result.success is False
        assert "Network error" in result.error


# ---------------------------------------------------------------------------
# last_rotation / next_rotation
# ---------------------------------------------------------------------------


class TestRotationStatus:
    def test_last_rotation_none_before_rotate(
        self, rotator: CredentialsRotator
    ) -> None:
        assert rotator.last_rotation("zerodha") is None

    def test_last_rotation_set_after_rotate(
        self, rotator: CredentialsRotator
    ) -> None:
        rotator.rotate_now("zerodha")
        ts = rotator.last_rotation("zerodha")
        assert ts is not None
        assert isinstance(ts, datetime)

    def test_next_rotation_none_without_schedule(
        self, rotator: CredentialsRotator
    ) -> None:
        assert rotator.next_rotation("zerodha") is None

    def test_next_rotation_set_after_schedule(
        self, rotator: CredentialsRotator
    ) -> None:
        rotator.schedule_daily_refresh("zerodha", "08:00")
        nxt = rotator.next_rotation("zerodha")
        assert nxt is not None

    def test_rotation_status_includes_all_brokers(
        self, rotator: CredentialsRotator
    ) -> None:
        rotator.rotate_now("zerodha")
        rotator.rotate_now("angel")
        brokers = {b["broker"] for b in rotator.rotation_status()}
        assert "zerodha" in brokers
        assert "angel" in brokers
