"""Extended tests for CronManager — job lifecycle, history, built-in jobs, holiday logic.

All external dependencies (APScheduler, OpenAlgo client) are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# JobDefinition & JobHistory dataclasses
# ---------------------------------------------------------------------------


class TestJobDefinitionDataclass:
    def test_default_status_is_active(self):
        from flinttrade_automation.cron_manager import JobDefinition, JobStatus
        job = JobDefinition(name="foo")
        assert job.status == JobStatus.ACTIVE.value

    def test_history_starts_empty(self):
        from flinttrade_automation.cron_manager import JobDefinition
        job = JobDefinition(name="foo")
        assert job.history == []

    def test_run_count_starts_zero(self):
        from flinttrade_automation.cron_manager import JobDefinition
        job = JobDefinition(name="foo")
        assert job.run_count == 0
        assert job.error_count == 0

    def test_max_history_default(self):
        from flinttrade_automation.cron_manager import JobDefinition
        job = JobDefinition(name="foo")
        assert job.max_history == 50

    def test_job_history_fields(self):
        from flinttrade_automation.cron_manager import JobHistory
        h = JobHistory(
            job_name="test",
            started_at="2026-03-16T09:10:00",
            finished_at="2026-03-16T09:10:01",
            success=True,
            duration_seconds=1.0,
        )
        assert h.job_name == "test"
        assert h.success is True
        assert h.duration_seconds == 1.0
        assert h.error == ""

    def test_job_history_error_field(self):
        from flinttrade_automation.cron_manager import JobHistory
        h = JobHistory(
            job_name="fail",
            started_at="now",
            success=False,
            error="connection refused",
        )
        assert h.error == "connection refused"
        assert not h.success


# ---------------------------------------------------------------------------
# JobStatus enum
# ---------------------------------------------------------------------------


class TestJobStatusEnum:
    def test_enum_values(self):
        from flinttrade_automation.cron_manager import JobStatus
        assert JobStatus.ACTIVE == "ACTIVE"
        assert JobStatus.PAUSED == "PAUSED"
        assert JobStatus.DISABLED == "DISABLED"

    def test_enum_is_str(self):
        from flinttrade_automation.cron_manager import JobStatus
        assert isinstance(JobStatus.ACTIVE, str)


# ---------------------------------------------------------------------------
# CronManager — registration
# ---------------------------------------------------------------------------


class TestCronManagerRegistration:
    def test_register_with_description(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("my_job", handler=MagicMock(), description="Run at midnight")
        jobs = cron.list_jobs()
        assert jobs[0]["description"] == "Run at midnight"

    def test_register_uses_default_job_config(self):
        """Registering a known job name picks up DEFAULT_JOBS description/trigger."""
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("backup")
        jobs = cron.list_jobs()
        assert jobs[0]["trigger_type"] == "cron"
        assert "backup" in jobs[0]["description"].lower()

    def test_register_overrides_default_description(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("backup", description="Custom backup desc")
        jobs = cron.list_jobs()
        assert jobs[0]["description"] == "Custom backup desc"

    def test_register_interval_trigger(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("poll", trigger_type="interval", trigger_args={"minutes": 1})
        jobs = cron.list_jobs()
        assert jobs[0]["trigger_type"] == "interval"

    def test_register_replaces_same_name(self):
        """Re-registering the same name should replace, not duplicate."""
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("job_x", handler=MagicMock(), description="v1")
        cron.register("job_x", handler=MagicMock(), description="v2")
        jobs = cron.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["description"] == "v2"

    def test_unregister_nonexistent_is_noop(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.unregister("does_not_exist")  # should not raise
        assert cron.list_jobs() == []

    def test_register_all_default_jobs(self):
        from flinttrade_automation.cron_manager import CronManager, DEFAULT_JOBS
        cron = CronManager()
        handlers = {name: MagicMock() for name in DEFAULT_JOBS}
        cron.register_defaults(handlers)
        registered_names = {j["name"] for j in cron.list_jobs()}
        assert registered_names == set(DEFAULT_JOBS.keys())

    def test_register_defaults_skips_missing_handlers(self):
        """register_defaults only registers jobs that have a handler provided."""
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register_defaults({"backup": MagicMock()})
        jobs = cron.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "backup"

    def test_list_jobs_returns_copy(self):
        """list_jobs() must return a fresh list each call."""
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j1", handler=MagicMock())
        first = cron.list_jobs()
        cron.register("j2", handler=MagicMock())
        second = cron.list_jobs()
        assert len(first) == 1
        assert len(second) == 2


# ---------------------------------------------------------------------------
# CronManager — job control (pause/resume/enable/disable)
# ---------------------------------------------------------------------------


class TestCronManagerControl:
    def test_stop_waits_for_inflight_jobs(self):
        from flinttrade_automation.cron_manager import CronManager

        cron = CronManager()
        cron._scheduler = MagicMock()
        cron._running = True

        cron.stop()

        cron._scheduler.shutdown.assert_called_once_with(wait=True)

    def _cron_with_job(self, name: str = "test_job"):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register(name, handler=MagicMock())
        return cron

    def test_pause_nonexistent_is_noop(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.pause("ghost")  # should not raise

    def test_resume_nonexistent_is_noop(self):
        cron = self._cron_with_job()
        cron.resume("ghost")  # should not raise

    def test_enable_nonexistent_is_noop(self):
        cron = self._cron_with_job()
        cron.enable("ghost")  # should not raise

    def test_disable_sets_disabled_status(self):
        from flinttrade_automation.cron_manager import JobStatus
        cron = self._cron_with_job()
        cron.disable("test_job")
        assert cron.list_jobs()[0]["status"] == JobStatus.DISABLED.value

    def test_enable_after_disable(self):
        from flinttrade_automation.cron_manager import JobStatus
        cron = self._cron_with_job()
        cron.disable("test_job")
        cron.enable("test_job")
        assert cron.list_jobs()[0]["status"] == JobStatus.ACTIVE.value

    def test_pause_sets_paused_status(self):
        from flinttrade_automation.cron_manager import JobStatus
        cron = self._cron_with_job()
        cron.pause("test_job")
        assert cron.list_jobs()[0]["status"] == JobStatus.PAUSED.value

    def test_resume_after_pause_restores_active(self):
        from flinttrade_automation.cron_manager import JobStatus
        cron = self._cron_with_job()
        cron.pause("test_job")
        cron.resume("test_job")
        assert cron.list_jobs()[0]["status"] == JobStatus.ACTIVE.value

    def test_paused_job_not_executed_by_run_now(self):
        from flinttrade_automation.cron_manager import CronManager
        handler = MagicMock()
        cron = CronManager()
        cron.register("paused_job", handler=handler)
        cron.pause("paused_job")
        cron.run_now("paused_job")
        handler.assert_not_called()

    def test_running_flag_starts_false(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        assert not cron.running


@pytest.mark.unit
def test_tick_retention_revalidates_provider_after_acquiring_lock() -> None:
    from flinttrade_automation.cron_manager import make_tick_retention_job

    state: dict[str, object | None] = {"storage": MagicMock()}

    class UnpublishingLock:
        def __enter__(self):
            state["storage"] = None

        def __exit__(self, *_args):
            return False

    lock = UnpublishingLock()
    storage = state["storage"]
    job = make_tick_retention_job(lambda: (state["storage"], lock, 90))

    job()

    storage.prune_ticks.assert_not_called()


@pytest.mark.unit
def test_db_optimise_revalidates_extra_store_after_acquiring_lock() -> None:
    from flinttrade_automation.cron_manager import make_db_optimise_job

    storage = MagicMock()
    state: dict[str, object | None] = {"storage": storage}

    class UnpublishingLock:
        def __enter__(self):
            state["storage"] = None

        def __exit__(self, *_args):
            return False

    lock = UnpublishingLock()
    job = make_db_optimise_job(
        extra_stores=lambda: [(state["storage"], lock, "tick")]
        if state["storage"] is not None
        else [],
    )

    job()

    assert storage.connection.execute.call_count == 0


# ---------------------------------------------------------------------------
# CronManager — execution and history tracking
# ---------------------------------------------------------------------------


class TestCronManagerExecution:
    def test_run_now_increments_run_count(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("counter", handler=MagicMock())
        cron.run_now("counter")
        cron.run_now("counter")
        jobs = cron.list_jobs()
        assert jobs[0]["run_count"] == 2

    def test_run_now_updates_last_run(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock())
        assert cron.list_jobs()[0]["last_run"] == ""
        cron.run_now("j")
        assert cron.list_jobs()[0]["last_run"] != ""

    def test_run_now_last_success_on_pass(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock())
        cron.run_now("j")
        assert cron.list_jobs()[0]["last_success"] is True

    def test_run_now_last_success_on_failure(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock(side_effect=ValueError("oops")))
        cron.run_now("j")
        assert cron.list_jobs()[0]["last_success"] is False

    def test_failure_increments_error_count(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock(side_effect=RuntimeError("fail")))
        cron.run_now("j")
        cron.run_now("j")
        assert cron.list_jobs()[0]["error_count"] == 2

    def test_success_does_not_increment_error_count(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock())
        cron.run_now("j")
        assert cron.list_jobs()[0]["error_count"] == 0

    def test_history_duration_is_positive(self):
        import time
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=lambda: time.sleep(0.01))
        cron.run_now("j")
        h = cron.get_history("j")
        assert h[0].duration_seconds >= 0.0

    def test_history_error_message_captured(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock(side_effect=ValueError("specific error")))
        cron.run_now("j")
        h = cron.get_history("j")
        assert "specific error" in h[0].error

    def test_history_capped_at_max_history(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("j", handler=MagicMock(), description="cap test")
        # Set max_history to 5
        cron._jobs["j"].max_history = 5
        for _ in range(10):
            cron.run_now("j")
        h = cron.get_history("j")
        assert len(h) == 5

    def test_get_history_unknown_job_returns_empty(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        assert cron.get_history("nonexistent") == []

    def test_run_now_nonexistent_job_is_noop(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.run_now("ghost")  # should not raise

    def test_run_now_job_without_handler_is_noop(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        cron.register("no_handler")  # no handler provided
        cron.run_now("no_handler")  # should not raise


# ---------------------------------------------------------------------------
# CronManager — holidays property
# ---------------------------------------------------------------------------


class TestCronManagerHolidays:
    def test_holidays_starts_empty(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        assert cron.holidays == set()

    def test_holidays_are_set_type(self):
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager()
        assert isinstance(cron.holidays, set)


# ---------------------------------------------------------------------------
# Holiday / market-day logic
# ---------------------------------------------------------------------------


class TestIsMarketHoliday:
    def test_saturday_is_holiday(self):
        from flinttrade_automation.cron_manager import _is_market_holiday
        # Patch datetime.now to return a Saturday
        saturday = datetime(2026, 3, 14, 10, 0, tzinfo=IST)
        with patch("flinttrade_automation.cron_manager.datetime") as mock_dt:
            mock_dt.now.return_value = saturday
            assert _is_market_holiday()

    def test_sunday_is_holiday(self):
        from flinttrade_automation.cron_manager import _is_market_holiday
        sunday = datetime(2026, 3, 15, 10, 0, tzinfo=IST)
        with patch("flinttrade_automation.cron_manager.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            assert _is_market_holiday()

    def test_weekday_not_in_holidays_is_not_holiday(self):
        from flinttrade_automation.cron_manager import _is_market_holiday
        monday = datetime(2026, 3, 16, 10, 0, tzinfo=IST)
        with patch("flinttrade_automation.cron_manager.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            assert not _is_market_holiday(holidays=set())

    def test_explicit_holiday_date_triggers(self):
        from flinttrade_automation.cron_manager import _is_market_holiday
        # Use a specific weekday that is in the holiday set
        # Monday 2026-03-23 as a mock holiday
        monday = datetime(2026, 3, 23, 10, 0, tzinfo=IST)
        with patch("flinttrade_automation.cron_manager.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            assert _is_market_holiday(holidays={"2026-03-23"})

    def test_weekday_not_in_holidays_set_is_false(self):
        from flinttrade_automation.cron_manager import _is_market_holiday
        monday = datetime(2026, 3, 23, 10, 0, tzinfo=IST)
        with patch("flinttrade_automation.cron_manager.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            # Holiday set does NOT contain this date
            assert not _is_market_holiday(holidays={"2026-01-01"})


# ---------------------------------------------------------------------------
# Built-in job factories
# ---------------------------------------------------------------------------


class TestBuiltinJobFactories:
    def _is_weekday(self) -> bool:
        return datetime.now(IST).date().weekday() < 5

    def test_health_check_job_on_weekday(self):
        """health_check_job pings OpenAlgo on a weekday, logs audit and Telegram."""
        from flinttrade_automation.cron_manager import make_health_check_job
        mock_client = MagicMock()
        mock_client.ping = MagicMock(return_value={"status": "success"})
        mock_audit = MagicMock()
        mock_bot = MagicMock()
        job = make_health_check_job(mock_client, mock_audit, mock_bot, holidays=set())
        if self._is_weekday():
            with patch("asyncio.run", return_value={"status": "success"}):
                job()
            mock_audit.log_event.assert_called()

    def test_health_check_job_on_holiday_skips(self):
        """health_check_job does nothing on a market holiday."""
        from flinttrade_automation.cron_manager import make_health_check_job
        mock_client = MagicMock()
        mock_audit = MagicMock()
        mock_bot = MagicMock()
        # Pass the current date as a holiday
        today_str = datetime.now(IST).date().isoformat()
        job = make_health_check_job(mock_client, mock_audit, mock_bot, holidays={today_str})
        job()
        mock_audit.log_event.assert_not_called()
        mock_bot.send_message.assert_not_called()

    def test_square_off_warning_on_holiday_skips(self):
        from flinttrade_automation.cron_manager import make_square_off_warning_job
        mock_bot = MagicMock()
        today_str = datetime.now(IST).date().isoformat()
        job = make_square_off_warning_job(mock_bot, holidays={today_str})
        job()
        mock_bot.send_message.assert_not_called()

    def test_eod_logout_on_holiday_skips(self):
        from flinttrade_automation.cron_manager import make_eod_logout_job
        mock_audit = MagicMock()
        today_str = datetime.now(IST).date().isoformat()
        job = make_eod_logout_job(mock_audit, holidays={today_str})
        job()
        mock_audit.log_event.assert_not_called()

    def test_health_check_job_no_audit_or_telegram(self):
        """health_check_job must not crash when audit/telegram are None."""
        from flinttrade_automation.cron_manager import make_health_check_job
        mock_client = MagicMock()
        job = make_health_check_job(mock_client, audit_logger=None, telegram_bot=None, holidays=set())
        if self._is_weekday():
            with patch("asyncio.run", return_value={"status": "success"}):
                job()  # should not raise

    def test_square_off_warning_no_telegram(self):
        from flinttrade_automation.cron_manager import make_square_off_warning_job
        job = make_square_off_warning_job(telegram_bot=None, holidays=set())
        if self._is_weekday():
            job()  # should not raise

    def test_eod_logout_no_audit(self):
        from flinttrade_automation.cron_manager import make_eod_logout_job
        job = make_eod_logout_job(audit_logger=None, holidays=set())
        if self._is_weekday():
            job()  # should not raise


# ---------------------------------------------------------------------------
# load_holidays_from_client
# ---------------------------------------------------------------------------


class TestLoadHolidays:
    def test_loads_holidays_list(self):
        import asyncio
        from flinttrade_automation.cron_manager import load_holidays_from_client
        mock_client = MagicMock()
        mock_client.holidays = MagicMock(
            return_value={"holidays": ["2026-01-01", "2026-01-26"]}
        )

        async def run():
            mock_client.holidays = _async_mock({"holidays": ["2026-01-01", "2026-01-26"]})
            return await load_holidays_from_client(mock_client)

        def _async_mock(retval):
            async def _inner():
                return retval
            return _inner

        mock_client.holidays = _async_mock({"holidays": ["2026-01-01", "2026-01-26"]})
        result = asyncio.run(load_holidays_from_client(mock_client))
        assert "2026-01-01" in result
        assert "2026-01-26" in result

    @pytest.mark.parametrize(
        "payload",
        [
            ["2026-04-14"],
            {"data": {"holidays": ["2026-04-14"]}},
            {"data": {"NSE": [{"date": "2026-04-14"}]}},
        ],
    )
    def test_loads_supported_openalgo_envelopes(self, payload):
        import asyncio
        from flinttrade_automation.cron_manager import load_holidays_from_client

        async def holidays():
            return payload

        result = asyncio.run(
            load_holidays_from_client(MagicMock(holidays=holidays))
        )

        assert result == {"2026-04-14"}

    def test_returns_empty_on_error(self):
        import asyncio
        from flinttrade_automation.cron_manager import load_holidays_from_client
        mock_client = MagicMock()

        async def _failing():
            raise RuntimeError("API down")

        mock_client.holidays = _failing
        result = asyncio.run(load_holidays_from_client(mock_client))
        assert result == set()

    def test_returns_empty_when_no_client(self):
        import asyncio
        from flinttrade_automation.cron_manager import CronManager
        cron = CronManager(openalgo_client=None)
        result = asyncio.run(cron.load_holidays())
        assert result == set()


# ---------------------------------------------------------------------------
# DEFAULT_JOBS constant
# ---------------------------------------------------------------------------


class TestDefaultJobsConfig:
    def test_all_required_jobs_present(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        required = {
            "health_check_job", "square_off_warning_job", "eod_logout_job",
            "health_check", "backup", "post_market_analysis", "mcx_close_check",
        }
        assert required.issubset(set(DEFAULT_JOBS.keys()))

    def test_health_check_interval_5_minutes(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        assert DEFAULT_JOBS["health_check"]["trigger_args"]["minutes"] == 5

    def test_backup_runs_at_midnight(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        assert DEFAULT_JOBS["backup"]["trigger_args"]["hour"] == 0
        assert DEFAULT_JOBS["backup"]["trigger_args"]["minute"] == 0

    def test_post_market_analysis_time(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        args = DEFAULT_JOBS["post_market_analysis"]["trigger_args"]
        assert args["hour"] == 15
        assert args["minute"] == 45

    def test_eod_logout_at_2345(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        args = DEFAULT_JOBS["eod_logout_job"]["trigger_args"]
        assert args["hour"] == 23
        assert args["minute"] == 45

    def test_no_totp_or_ddns_jobs(self):
        """TOTP auto-login and DDNS update are not part of FlintTrade."""
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        assert "totp_login" not in DEFAULT_JOBS
        assert "ddns_update" not in DEFAULT_JOBS

    def test_all_jobs_have_trigger_type(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        for name, config in DEFAULT_JOBS.items():
            assert "trigger_type" in config, f"Job '{name}' missing trigger_type"

    def test_all_jobs_have_trigger_args(self):
        from flinttrade_automation.cron_manager import DEFAULT_JOBS
        for name, config in DEFAULT_JOBS.items():
            assert "trigger_args" in config, f"Job '{name}' missing trigger_args"


class TestDbOptimiseJob:
    """Nightly DuckDB maintenance job (CHECKPOINT + ANALYZE)."""

    def test_runs_checkpoint_and_analyze_under_lock(self):
        import threading

        from flinttrade_automation.cron_manager import make_db_optimise_job

        conn = MagicMock()
        storage = MagicMock()
        storage.connection = conn
        lock = threading.Lock()

        job = make_db_optimise_job(storage, lock)
        job()

        executed = [c.args[0] for c in conn.execute.call_args_list]
        assert "CHECKPOINT" in executed
        assert "ANALYZE" in executed
        assert not lock.locked()  # released after the job

    def test_no_storage_is_a_safe_noop(self):
        from flinttrade_automation.cron_manager import make_db_optimise_job

        # Must not raise when no store is configured.
        make_db_optimise_job(None)()

    def test_failure_never_raises(self):
        from flinttrade_automation.cron_manager import make_db_optimise_job

        storage = MagicMock()
        storage.connection.execute.side_effect = RuntimeError("duckdb locked")
        # Best-effort: a maintenance failure must be swallowed.
        make_db_optimise_job(storage)()

    def test_registered_only_when_trade_storage_present(self):
        from flinttrade_automation.cron_manager import CronManager

        without = CronManager()
        without.register_builtin_jobs()
        assert "db_optimise_job" not in {j["name"] for j in without.list_jobs()}

        storage = MagicMock()
        with_store = CronManager(trade_storage=storage)
        with_store.register_builtin_jobs()
        assert "db_optimise_job" in {j["name"] for j in with_store.list_jobs()}

    def test_maintains_both_trade_and_tick_stores(self):
        from flinttrade_automation.cron_manager import make_db_optimise_job

        trade = MagicMock()
        tick = MagicMock()
        job = make_db_optimise_job(trade, None, extra_stores=lambda: [(tick, None, "tick")])
        job()

        for store in (trade, tick):
            executed = [c.args[0] for c in store.connection.execute.call_args_list]
            assert "CHECKPOINT" in executed and "ANALYZE" in executed

    def test_tick_store_is_resolved_lazily_at_fire_time(self):
        # The tick store is wired AFTER register_builtin_jobs runs, so the job
        # must read it at fire time. Mirror that: provider returns None first,
        # then the real store — only the second run maintains it.
        from flinttrade_automation.cron_manager import make_db_optimise_job

        holder: dict[str, object] = {"tick": None}
        trade = MagicMock()
        job = make_db_optimise_job(
            trade, None, extra_stores=lambda: [(holder["tick"], None, "tick")],
        )

        job()  # tick not wired yet → only trade maintained, no crash
        tick = MagicMock()
        holder["tick"] = tick
        job()  # tick now wired → maintained

        executed = [c.args[0] for c in tick.connection.execute.call_args_list]
        assert "CHECKPOINT" in executed and "ANALYZE" in executed


class TestTickRetentionJob:
    """Nightly tick-store pruning job."""

    def test_prunes_under_the_shared_lock(self):
        import threading

        from flinttrade_automation.cron_manager import make_tick_retention_job

        storage = MagicMock()
        storage.prune_ticks.return_value = 5
        lock = threading.Lock()

        make_tick_retention_job(lambda: (storage, lock, 30))()

        storage.prune_ticks.assert_called_once_with(30)
        assert not lock.locked()  # released after the job

    def test_noop_without_a_store_or_a_positive_window(self):
        from flinttrade_automation.cron_manager import make_tick_retention_job

        storage = MagicMock()
        make_tick_retention_job(lambda: (None, None, 30))()   # no store
        make_tick_retention_job(lambda: (storage, None, 0))()  # disabled window
        storage.prune_ticks.assert_not_called()

    def test_failure_never_raises(self):
        from flinttrade_automation.cron_manager import make_tick_retention_job

        storage = MagicMock()
        storage.prune_ticks.side_effect = RuntimeError("duckdb locked")
        # Best-effort: a prune failure must be swallowed.
        make_tick_retention_job(lambda: (storage, None, 30))()

    def test_registered_alongside_db_optimise(self):
        from flinttrade_automation.cron_manager import CronManager

        with_store = CronManager(trade_storage=MagicMock())
        with_store.register_builtin_jobs()
        names = {j["name"] for j in with_store.list_jobs()}
        assert "tick_retention_job" in names

    def test_registered_without_trade_storage(self):
        from flinttrade_automation.cron_manager import CronManager

        without_trade_store = CronManager()
        without_trade_store.register_builtin_jobs()

        names = {job["name"] for job in without_trade_store.list_jobs()}
        assert "db_optimise_job" not in names
        assert "tick_retention_job" in names


class TestEodSyncJob:
    """eod_sync_job — daily historical-data delta sync (opt-in)."""

    def test_calls_starter_on_trading_day(self):
        from flinttrade_automation.cron_manager import make_eod_sync_job

        starter = MagicMock(return_value=MagicMock(job_id="job-1"))
        with patch(
            "flinttrade_automation.cron_manager._is_market_holiday", return_value=False
        ):
            make_eod_sync_job(starter)()
        starter.assert_called_once_with()

    def test_skips_on_holiday(self):
        from flinttrade_automation.cron_manager import make_eod_sync_job

        starter = MagicMock()
        with patch(
            "flinttrade_automation.cron_manager._is_market_holiday", return_value=True
        ):
            make_eod_sync_job(starter)()
        starter.assert_not_called()

    def test_swallows_starter_failure(self):
        from flinttrade_automation.cron_manager import make_eod_sync_job

        starter = MagicMock(side_effect=RuntimeError("openalgo down"))
        with patch(
            "flinttrade_automation.cron_manager._is_market_holiday", return_value=False
        ):
            make_eod_sync_job(starter)()  # must not raise

    def test_none_job_logged_not_raised(self):
        from flinttrade_automation.cron_manager import make_eod_sync_job

        starter = MagicMock(return_value=None)  # empty watchlist
        with patch(
            "flinttrade_automation.cron_manager._is_market_holiday", return_value=False
        ):
            make_eod_sync_job(starter)()

    def test_registered_only_when_starter_injected(self):
        from flinttrade_automation.cron_manager import CronManager

        without = CronManager()
        without.register_builtin_jobs()
        assert "eod_sync_job" not in {j["name"] for j in without.list_jobs()}

        with_starter = CronManager()
        with_starter.eod_sync_starter = MagicMock()
        with_starter.register_builtin_jobs()
        assert "eod_sync_job" in {j["name"] for j in with_starter.list_jobs()}
