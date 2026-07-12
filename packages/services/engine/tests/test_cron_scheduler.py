"""Tests for CronStrategyScheduler — cron-based strategy scheduling.

Covers:
- Cron expression parsing (valid, invalid, edge cases)
- schedule() / unschedule() lifecycle
- list_jobs() introspection
- Market-hours gate: weekends, holidays, outside hours, inside hours
- Multi-exchange gating (NSE vs MCX different hours)
- 24×7 exchange (DELTA) never skipped by hours check
- REST endpoints: POST /<id>/schedule, DELETE /<id>/schedule, GET /scheduled
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from flinttrade_engine.scheduler import (
    CronScheduleConfig,
    CronStrategyScheduler,
    TimeScheduler,
)

# IST offset for constructing aware datetime objects in tests
_IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ist(h: int, m: int, weekday: int = 0, is_holiday: bool = False) -> tuple[datetime, date]:
    """Return an IST datetime and its date at the given hour:minute.

    Args:
        h: Hour (0-23).
        m: Minute (0-59).
        weekday: 0=Monday … 4=Friday, 5=Saturday, 6=Sunday.
        is_holiday: Whether the date should be treated as a holiday in mocks.

    Returns:
        Tuple (datetime_ist, date).
    """
    # Build a Monday (2026-04-13) + weekday offset as a base
    base_monday = date(2026, 4, 13)
    target_date = base_monday + timedelta(days=weekday)
    dt = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        h,
        m,
        0,
        tzinfo=_IST,
    )
    return dt, target_date


def _make_scheduler(
    holidays: list[str] | None = None,
    check_market: bool = True,
) -> CronStrategyScheduler:
    """Create a CronStrategyScheduler with a pre-loaded TimeScheduler."""
    ts = TimeScheduler()
    if holidays:
        ts._holidays[str(date(2026, 4, 13).year)] = holidays
    return CronStrategyScheduler(time_scheduler=ts, market_hours_check=check_market)


@pytest.mark.parametrize(
    ("at", "holidays"),
    [
        (_ist(10, 0, weekday=5)[0], []),
        (_ist(10, 0, weekday=0)[0], ["2026-04-13"]),
    ],
)
def test_time_scheduler_market_open_requires_trading_calendar(
    at: datetime,
    holidays: list[str],
) -> None:
    scheduler = TimeScheduler()
    scheduler._holidays[str(at.year)] = holidays

    assert scheduler.is_market_open("NSE", at=at) is False


# ---------------------------------------------------------------------------
# _parse_cron_expr
# ---------------------------------------------------------------------------


class TestParseCronExpr:
    def test_valid_weekday_expression(self) -> None:
        parts = CronStrategyScheduler._parse_cron_expr("30 9 * * 1-5")
        assert parts == {
            "minute": "30",
            "hour": "9",
            "day": "*",
            "month": "*",
            "day_of_week": "0-4",
        }

    def test_valid_every_minute(self) -> None:
        parts = CronStrategyScheduler._parse_cron_expr("* * * * *")
        assert parts["minute"] == "*"
        assert parts["day_of_week"] == "*"

    def test_valid_specific_fields(self) -> None:
        parts = CronStrategyScheduler._parse_cron_expr("0 15 * * 1,2,3,4,5")
        assert parts["minute"] == "0"
        assert parts["hour"] == "15"
        assert parts["day_of_week"] == "0,1,2,3,4"

    @pytest.mark.parametrize(("standard", "apscheduler"), [("0", "6"), ("7", "6"), ("1", "0")])
    def test_numeric_weekdays_translate_from_sunday_zero(
        self,
        standard: str,
        apscheduler: str,
    ) -> None:
        parts = CronStrategyScheduler._parse_cron_expr(f"0 9 * * {standard}")
        assert parts["day_of_week"] == apscheduler

    @pytest.mark.parametrize(
        ("standard", "apscheduler"),
        [
            ("0-6", "6,0,1,2,3,4,5"),
            ("1-7", "0-6"),
            ("*/2", "6,1,3,5"),
            ("0/2", "6,1,3,5"),
            ("mon,3", "mon,2"),
        ],
    )
    def test_numeric_weekday_ranges_and_steps_preserve_standard_semantics(
        self,
        standard: str,
        apscheduler: str,
    ) -> None:
        parts = CronStrategyScheduler._parse_cron_expr(f"0 9 * * {standard}")
        assert parts["day_of_week"] == apscheduler
        CronStrategyScheduler._build_cron_trigger(parts)

    @pytest.mark.parametrize("weekday", ["8", "5-1"])
    def test_invalid_numeric_weekday_fails_closed(self, weekday: str) -> None:
        with pytest.raises(ValueError):
            CronStrategyScheduler._parse_cron_expr(f"0 9 * * {weekday}")

    def test_too_few_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            CronStrategyScheduler._parse_cron_expr("30 9 * *")

    def test_too_many_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            CronStrategyScheduler._parse_cron_expr("30 9 * * 1-5 extra")

    def test_empty_expression_raises(self) -> None:
        with pytest.raises(ValueError, match="expected 5 fields"):
            CronStrategyScheduler._parse_cron_expr("")

    def test_whitespace_trimmed(self) -> None:
        parts = CronStrategyScheduler._parse_cron_expr("  0 9 * * mon-fri  ")
        assert parts["minute"] == "0"
        assert parts["day_of_week"] == "mon-fri"


# ---------------------------------------------------------------------------
# schedule / unschedule (no APScheduler)
# ---------------------------------------------------------------------------


class TestScheduleLifecycle:
    """Tests that do not require APScheduler to be running."""

    def test_exposes_injected_time_scheduler_for_runtime_calendar_sharing(self) -> None:
        time_scheduler = TimeScheduler()

        sched = CronStrategyScheduler(time_scheduler=time_scheduler)

        assert sched.time_scheduler is time_scheduler

    def test_start_registers_callback_scheduled_before_start(self) -> None:
        sched = _make_scheduler(check_market=False)
        fired: list[bool] = []
        pending_job_id = sched.schedule(
            "deferred",
            "30 9 * * 1-5",
            lambda: fired.append(True),
        )
        backend = MagicMock()

        with (
            patch(
                "apscheduler.schedulers.background.BackgroundScheduler",
                return_value=backend,
            ),
            patch.object(
                sched,
                "_add_apscheduler_job",
                return_value="deferred",
            ) as add_job,
        ):
            sched.start()

        assert pending_job_id == "pending:deferred"
        add_job.assert_called_once()
        registered_callback = add_job.call_args.args[2]
        registered_callback()
        assert fired == [True]
        assert sched.get_schedule("deferred").job_id == "deferred"

    def test_schedule_stores_config(self) -> None:
        sched = _make_scheduler()
        fired: list[bool] = []
        sched.schedule("s1", "30 9 * * 1-5", lambda: fired.append(True))

        cfg = sched.get_schedule("s1")
        assert cfg is not None
        assert cfg.strategy_id == "s1"
        assert cfg.cron_expr == "30 9 * * 1-5"
        assert cfg.exchange == "NSE"  # default

    def test_schedule_normalises_exchange_to_upper(self) -> None:
        sched = _make_scheduler()
        sched.schedule("s2", "0 9 * * 1-5", lambda: None, exchange="nse")
        assert sched.get_schedule("s2").exchange == "NSE"

    def test_schedule_invalid_cron_raises(self) -> None:
        sched = _make_scheduler()
        with pytest.raises(ValueError, match="expected 5 fields"):
            sched.schedule("s3", "bad cron", lambda: None)

    def test_schedule_empty_strategy_id_raises(self) -> None:
        sched = _make_scheduler()
        with pytest.raises(ValueError, match="non-empty"):
            sched.schedule("", "30 9 * * 1-5", lambda: None)

    def test_unschedule_existing_returns_true(self) -> None:
        sched = _make_scheduler()
        sched.schedule("s4", "30 9 * * 1-5", lambda: None)
        assert sched.unschedule("s4") is True
        assert sched.get_schedule("s4") is None

    def test_unschedule_missing_returns_false(self) -> None:
        sched = _make_scheduler()
        assert sched.unschedule("nonexistent") is False

    def test_list_jobs_empty(self) -> None:
        sched = _make_scheduler()
        assert sched.list_jobs() == []

    def test_list_jobs_returns_all(self) -> None:
        sched = _make_scheduler()
        sched.schedule("sa", "30 9 * * 1-5", lambda: None, exchange="NSE")
        sched.schedule("sb", "0 9 * * 1-5", lambda: None, exchange="MCX")
        jobs = sched.list_jobs()
        ids = {j["strategy_id"] for j in jobs}
        assert ids == {"sa", "sb"}

    def test_list_jobs_fields_present(self) -> None:
        sched = _make_scheduler()
        sched.schedule("sc", "30 9 * * 1-5", lambda: None)
        job = sched.list_jobs()[0]
        assert "strategy_id" in job
        assert "cron_expr" in job
        assert "exchange" in job
        assert "job_id" in job
        assert "last_skipped_reason" in job
        assert "next_fire_time" in job

    def test_reschedule_overwrites_previous(self) -> None:
        sched = _make_scheduler()
        sched.schedule("sd", "30 9 * * 1-5", lambda: None)
        sched.schedule("sd", "0 15 * * 1-5", lambda: None)
        assert sched.get_schedule("sd").cron_expr == "0 15 * * 1-5"

    def test_invalid_running_replacement_preserves_removable_old_job(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "atomic"
        sched._scheduler = backend
        sched._running = True

        def old_callback() -> None:
            pass

        sched.schedule("atomic", "30 9 * * 1-5", old_callback)
        old_config = sched.get_schedule("atomic")
        old_wrapped = sched._callbacks["atomic"]

        with pytest.raises(ValueError):
            sched.schedule("atomic", "99 9 * * 1-5", lambda: None)

        assert sched.get_schedule("atomic") is old_config
        assert sched._callbacks["atomic"] is old_wrapped
        assert sched.unschedule("atomic") is True
        backend.remove_job.assert_called_once_with("atomic")

    def test_queued_callback_does_not_run_after_unschedule(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "queued"
        sched._scheduler = backend
        sched._running = True
        fired: list[str] = []
        sched.schedule("queued", "30 9 * * 1-5", lambda: fired.append("fired"))
        queued_callback = sched._callbacks["queued"]

        sched.unschedule("queued")
        queued_callback()

        assert fired == []

    def test_queued_callback_does_not_run_after_stop(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "stopped"
        sched._scheduler = backend
        sched._running = True
        fired: list[str] = []
        sched.schedule("stopped", "30 9 * * 1-5", lambda: fired.append("fired"))
        queued_callback = sched._callbacks["stopped"]

        sched.stop()
        queued_callback()

        assert fired == []

    def test_failed_backend_shutdown_remains_owned_and_retryable(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.shutdown.side_effect = [RuntimeError("backend busy"), None]
        sched._scheduler = backend
        sched._running = True

        with pytest.raises(RuntimeError, match="backend busy"):
            sched.stop()

        assert sched.running is False
        assert sched._scheduler is backend
        with pytest.raises(RuntimeError, match="previous backend"):
            sched.start()

        sched.stop()

        assert sched._scheduler is None
        assert backend.shutdown.call_count == 2

    def test_stop_waits_for_already_admitted_callback(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "running"
        sched._scheduler = backend
        sched._running = True
        callback_entered = threading.Event()
        release_callback = threading.Event()
        stop_finished = threading.Event()

        def slow_callback() -> None:
            callback_entered.set()
            assert release_callback.wait(timeout=2)

        sched.schedule("running", "30 9 * * 1-5", slow_callback)
        queued_callback = sched._callbacks["running"]
        callback_thread = threading.Thread(target=queued_callback)
        stop_thread = threading.Thread(target=lambda: (sched.stop(), stop_finished.set()))
        callback_thread.start()
        assert callback_entered.wait(timeout=2)
        stop_thread.start()

        try:
            assert not stop_finished.wait(timeout=0.1)
        finally:
            release_callback.set()
            callback_thread.join(timeout=2)
            stop_thread.join(timeout=2)

        assert stop_finished.is_set()
        assert not callback_thread.is_alive()
        assert not stop_thread.is_alive()
        backend.shutdown.assert_called_once_with(wait=False)

    def test_callback_drain_timeout_retains_backend_for_stop_retry(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "running"
        sched._scheduler = backend
        sched._running = True
        callback_entered = threading.Event()
        release_callback = threading.Event()

        def slow_callback() -> None:
            callback_entered.set()
            assert release_callback.wait(timeout=2)

        sched.schedule("running", "30 9 * * 1-5", slow_callback)
        callback_thread = threading.Thread(target=sched._callbacks["running"])
        callback_thread.start()
        assert callback_entered.wait(timeout=2)

        try:
            with pytest.raises(RuntimeError, match="callbacks did not stop"):
                sched.stop(timeout=0.01)
        finally:
            release_callback.set()
            callback_thread.join(timeout=2)

        assert sched._scheduler is backend
        with pytest.raises(RuntimeError, match="previous backend"):
            sched.start()

        sched.stop(timeout=1.0)

        assert sched._scheduler is None
        backend.shutdown.assert_called_once_with(wait=False)

    def test_queued_callback_from_replaced_generation_does_not_run(self) -> None:
        sched = _make_scheduler(check_market=False)
        backend = MagicMock()
        backend.add_job.return_value.id = "generation"
        sched._scheduler = backend
        sched._running = True
        fired: list[str] = []
        sched.schedule("generation", "30 9 * * 1-5", lambda: fired.append("old"))
        old_callback = sched._callbacks["generation"]
        sched.schedule("generation", "0 10 * * 1-5", lambda: fired.append("new"))
        new_callback = sched._callbacks["generation"]

        old_callback()
        new_callback()

        assert fired == ["new"]

    def test_concurrent_replacements_serialize_backend_and_state_commit(self) -> None:
        sched = _make_scheduler(check_market=False)
        sched._scheduler = MagicMock()
        sched._running = True
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        call_count = 0
        call_count_lock = threading.Lock()
        errors: list[Exception] = []

        def add_job(*_args: Any) -> str:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_entered.set()
                assert release_first.wait(timeout=2)
            else:
                second_entered.set()
            return "concurrent"

        def replace(cron_expr: str) -> None:
            try:
                sched.schedule("concurrent", cron_expr, lambda: None)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with patch.object(sched, "_add_apscheduler_job", side_effect=add_job):
            first = threading.Thread(target=replace, args=("30 9 * * 1-5",))
            second = threading.Thread(target=replace, args=("0 10 * * 1-5",))
            first.start()
            assert first_entered.wait(timeout=2)
            second.start()

            assert not second_entered.wait(timeout=0.1)
            release_first.set()
            first.join(timeout=2)
            second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert errors == []
        assert sched.get_schedule("concurrent").cron_expr == "0 10 * * 1-5"


# ---------------------------------------------------------------------------
# Market-hours gate (unit-tested via the wrapped callback directly)
# ---------------------------------------------------------------------------


class TestMarketHoursGate:
    """Invoke the gated callback directly without APScheduler."""

    def _get_gated(
        self,
        exchange: str = "NSE",
        holidays: list[str] | None = None,
    ) -> tuple[list[bool], CronScheduleConfig, Any]:
        """Register a strategy and return (fired_list, config, gated_callable)."""
        sched = _make_scheduler(holidays=holidays)
        fired: list[bool] = []
        sched.schedule("gate-test", "30 9 * * 1-5", lambda: fired.append(True), exchange=exchange)
        cfg = sched.get_schedule("gate-test")
        # Re-build gated callback to get a fresh reference
        gated = sched._make_gated_callback("gate-test", lambda: fired.append(True), cfg)
        return fired, cfg, gated

    # --- check_market=False bypass ---

    def test_no_check_always_fires(self) -> None:
        sched = CronStrategyScheduler(market_hours_check=False)
        fired: list[bool] = []
        sched.schedule("bypass", "30 9 * * 1-5", lambda: fired.append(True))
        cfg = sched.get_schedule("bypass")
        gated = sched._make_gated_callback("bypass", lambda: fired.append(True), cfg)
        # Patch datetime to a Saturday — should still fire
        saturday_ist = datetime(2026, 4, 18, 9, 30, tzinfo=_IST)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = saturday_ist
            gated()
        assert len(fired) == 1

    # --- Weekend skip ---

    def test_saturday_skipped(self) -> None:
        fired, cfg, gated = self._get_gated()
        sat_dt, sat_date = _ist(9, 30, weekday=5)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sat_dt
            gated()
        assert len(fired) == 0
        assert "weekend" in cfg.last_skipped_reason

    def test_sunday_skipped(self) -> None:
        fired, cfg, gated = self._get_gated()
        sun_dt, _ = _ist(9, 30, weekday=6)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = sun_dt
            gated()
        assert len(fired) == 0

    def test_weekend_special_session_uses_time_scheduler_calendar(self) -> None:
        time_scheduler = TimeScheduler()
        time_scheduler.set_holidays(
            {
                "data": [
                    {
                        "date": "2026-11-08",
                        "holiday_type": "SPECIAL_SESSION",
                        "closed_exchanges": ["NSE"],
                        "open_exchanges": [
                            {
                                "exchange": "NSE",
                                "start_time": "18:00",
                                "end_time": "19:00",
                            }
                        ],
                    }
                ]
            },
            year="2026",
        )
        scheduler = CronStrategyScheduler(time_scheduler=time_scheduler)
        fired: list[bool] = []
        config = CronScheduleConfig(
            strategy_id="weekend-special",
            cron_expr="5 18 * * *",
            exchange="NSE",
        )
        gated = scheduler._make_gated_callback(
            config.strategy_id,
            lambda: fired.append(True),
            config,
        )

        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 11, 8, 18, 5, tzinfo=_IST)
            gated()

        assert fired == [True]
        assert config.last_skipped_reason == ""

    def test_weekday_dynamic_session_uses_time_scheduler_hours(self) -> None:
        time_scheduler = TimeScheduler()
        time_scheduler.set_holidays(
            {
                "data": [
                    {
                        "date": "2026-04-13",
                        "holiday_type": "SPECIAL_SESSION",
                        "closed_exchanges": ["NSE"],
                        "open_exchanges": [
                            {
                                "exchange": "NSE",
                                "start_time": "18:00",
                                "end_time": "19:00",
                            }
                        ],
                    }
                ]
            },
            year="2026",
        )
        scheduler = CronStrategyScheduler(time_scheduler=time_scheduler)
        fired: list[bool] = []
        config = CronScheduleConfig(
            strategy_id="weekday-special",
            cron_expr="30 18 * * *",
            exchange="NSE",
        )
        gated = scheduler._make_gated_callback(
            config.strategy_id,
            lambda: fired.append(True),
            config,
        )

        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 13, 18, 30, tzinfo=_IST)
            gated()

        assert fired == [True]
        assert config.last_skipped_reason == ""

    def test_symbol_scoped_schedule_carries_symbol_into_market_gate(self) -> None:
        time_scheduler = TimeScheduler()
        time_scheduler.set_holidays(
            {
                "data": [
                    {
                        "date": "2026-12-12",
                        "holiday_type": "SPECIAL_SESSION",
                        "closed_exchanges": ["CDS"],
                        "open_exchanges": [
                            {
                                "exchange": "CDS",
                                "symbols": ["EURUSD"],
                                "start_time": "18:00:30",
                                "end_time": "19:00:45",
                            }
                        ],
                    }
                ]
            },
            year="2026",
        )
        scheduler = CronStrategyScheduler(time_scheduler=time_scheduler)
        fired: list[bool] = []
        scheduler.schedule(
            "currency-special",
            "1 18 * * *",
            lambda: fired.append(True),
            exchange="CDS",
            symbol="eurusd29jul26fut",
        )
        config = scheduler.get_schedule("currency-special")
        gated = scheduler._make_gated_callback(
            config.strategy_id,
            lambda: fired.append(True),
            config,
        )

        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 12, 12, 18, 1, tzinfo=_IST)
            gated()

        assert config.symbol == "EURUSD29JUL26FUT"
        assert fired == [True]

    # --- Holiday skip ---

    def test_market_holiday_skipped(self) -> None:
        # Monday 2026-04-13 marked as holiday
        holiday_date = "2026-04-13"
        fired, cfg, gated = self._get_gated(holidays=[holiday_date])
        mon_dt, _ = _ist(9, 30, weekday=0)  # Monday
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = mon_dt
            # Directly invoke gated — TimeScheduler checks _holidays dict
            gated()
        assert len(fired) == 0
        assert "holiday" in cfg.last_skipped_reason

    # --- Outside market hours skip ---

    def test_before_market_open_nse_skipped(self) -> None:
        fired, cfg, gated = self._get_gated(exchange="NSE")
        # 08:00 IST — before NSE opens at 09:15
        early_dt, _ = _ist(8, 0, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = early_dt
            gated()
        assert len(fired) == 0
        assert "outside market hours" in cfg.last_skipped_reason

    def test_after_market_close_nse_skipped(self) -> None:
        fired, cfg, gated = self._get_gated(exchange="NSE")
        # 16:00 IST — after NSE closes at 15:30
        late_dt, _ = _ist(16, 0, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = late_dt
            gated()
        assert len(fired) == 0
        assert "outside market hours" in cfg.last_skipped_reason

    # --- Inside market hours fires ---

    def test_inside_nse_hours_fires(self) -> None:
        fired, cfg, gated = self._get_gated(exchange="NSE")
        # 09:30 IST — inside NSE hours
        ok_dt, _ = _ist(9, 30, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = ok_dt
            gated()
        assert len(fired) == 1
        assert cfg.last_skipped_reason == ""

    def test_at_market_open_nse_fires(self) -> None:
        fired, cfg, gated = self._get_gated(exchange="NSE")
        # Exactly 09:15 IST
        open_dt, _ = _ist(9, 15, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = open_dt
            gated()
        assert len(fired) == 1

    def test_at_market_close_nse_fires(self) -> None:
        fired, cfg, gated = self._get_gated(exchange="NSE")
        # Exactly 15:30 IST (boundary is inclusive)
        close_dt, _ = _ist(15, 30, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = close_dt
            gated()
        assert len(fired) == 1


# ---------------------------------------------------------------------------
# Multi-exchange: NSE vs MCX
# ---------------------------------------------------------------------------


class TestMultiExchange:
    """Different hours for different exchanges."""

    def _gated_for(self, exchange: str, h: int, m: int, weekday: int = 0) -> tuple[list[bool], Any]:
        sched = _make_scheduler()
        fired: list[bool] = []
        sched.schedule("x", "0 * * * *", lambda: fired.append(True), exchange=exchange)
        cfg = sched.get_schedule("x")
        gated = sched._make_gated_callback("x", lambda: fired.append(True), cfg)
        dt, _ = _ist(h, m, weekday=weekday)
        return fired, (gated, dt)

    def test_mcx_fires_at_21_00_nse_would_not(self) -> None:
        """21:00 IST is outside NSE hours but inside MCX hours."""
        fired_mcx, (gated_mcx, dt) = self._gated_for("MCX", 21, 0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated_mcx()
        assert len(fired_mcx) == 1

    def test_nse_skips_at_21_00(self) -> None:
        fired_nse, (gated_nse, dt) = self._gated_for("NSE", 21, 0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated_nse()
        assert len(fired_nse) == 0

    def test_nse_fires_at_10_00(self) -> None:
        fired, (gated, dt) = self._gated_for("NSE", 10, 0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated()
        assert len(fired) == 1

    def test_mcx_skips_before_open(self) -> None:
        """08:00 IST is before MCX opens at 09:00."""
        fired, (gated, dt) = self._gated_for("MCX", 8, 0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated()
        assert len(fired) == 0


# ---------------------------------------------------------------------------
# 24x7 exchange (DELTA)
# ---------------------------------------------------------------------------


class TestDelta24x7:
    """DELTA exchange is 24×7 — weekend and hours checks do not apply."""

    def _gated_delta(self, h: int, m: int, weekday: int) -> tuple[list[bool], Any]:
        sched = _make_scheduler()
        fired: list[bool] = []
        sched.schedule("d", "0 * * * *", lambda: fired.append(True), exchange="DELTA")
        cfg = sched.get_schedule("d")
        gated = sched._make_gated_callback("d", lambda: fired.append(True), cfg)
        dt, _ = _ist(h, m, weekday=weekday)
        return fired, (gated, dt)

    def test_delta_fires_on_saturday(self) -> None:
        fired, (gated, dt) = self._gated_delta(12, 0, weekday=5)  # Saturday
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated()
        assert len(fired) == 1

    def test_delta_fires_at_midnight(self) -> None:
        fired, (gated, dt) = self._gated_delta(0, 0, weekday=0)
        with patch("flinttrade_engine.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = dt
            gated()
        assert len(fired) == 1


# ---------------------------------------------------------------------------
# CronScheduleConfig dataclass
# ---------------------------------------------------------------------------


class TestCronScheduleConfig:
    def test_default_exchange(self) -> None:
        cfg = CronScheduleConfig(strategy_id="s", cron_expr="30 9 * * 1-5")
        assert cfg.exchange == "NSE"

    def test_default_job_id_empty(self) -> None:
        cfg = CronScheduleConfig(strategy_id="s", cron_expr="30 9 * * 1-5")
        assert cfg.job_id == ""

    def test_last_skipped_reason_default_empty(self) -> None:
        cfg = CronScheduleConfig(strategy_id="s", cron_expr="30 9 * * 1-5")
        assert cfg.last_skipped_reason == ""

    def test_mutable_last_skipped_reason(self) -> None:
        cfg = CronScheduleConfig(strategy_id="s", cron_expr="30 9 * * 1-5")
        cfg.last_skipped_reason = "weekend (Saturday)"
        assert cfg.last_skipped_reason == "weekend (Saturday)"


# ---------------------------------------------------------------------------
# REST endpoint tests (via Flask test client)
# ---------------------------------------------------------------------------


@pytest.fixture()
def flask_app():
    """Create a minimal Flask app with strategy runner and cron scheduler mocked."""
    from flask import Flask

    app = Flask(__name__)
    app.config["TESTING"] = True

    # Minimal mock runner that tracks a known strategy id
    mock_runner = MagicMock()
    mock_runner.get_status.return_value = {"state": "stopped", "strategy_id": "strat-001"}
    mock_runner.start.return_value = None

    cron_sched = _make_scheduler()

    from flinttrade_engine.strategy_routes import strategy_bp

    app.register_blueprint(strategy_bp)
    app.config["STRATEGY_RUNNER"] = mock_runner
    app.config["CRON_SCHEDULER"] = cron_sched

    return app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


class TestCronRestEndpoints:

    # --- POST /<id>/schedule ---

    def test_create_schedule_success(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "30 9 * * 1-5", "exchange": "NSE"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["strategy_id"] == "strat-001"
        assert data["data"]["cron"] == "30 9 * * 1-5"
        assert data["data"]["exchange"] == "NSE"
        assert "job_id" in data["data"]

    def test_create_schedule_default_exchange(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "0 9 * * 1-5"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["exchange"] == "NSE"

    def test_create_schedule_lowercase_exchange_normalised(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "0 9 * * 1-5", "exchange": "mcx"},
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["exchange"] == "MCX"

    def test_create_and_list_schedule_preserves_symbol(self, client, flask_app) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={
                "cron": "0 9 * * 1-5",
                "exchange": "CDS",
                "symbol": "eurusd29jul26fut",
            },
        )

        assert resp.status_code == 201
        assert resp.get_json()["data"]["symbol"] == "EURUSD29JUL26FUT"
        assert flask_app.config["CRON_SCHEDULER"].get_schedule("strat-001").symbol == "EURUSD29JUL26FUT"

        listed = client.get("/api/v1/strategies/scheduled").get_json()["data"]["schedules"]
        assert listed[0]["symbol"] == "EURUSD29JUL26FUT"

    def test_create_schedule_missing_cron(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"exchange": "NSE"},
        )
        assert resp.status_code == 400
        assert "cron" in resp.get_json()["message"].lower()

    def test_create_schedule_invalid_cron(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "not a cron"},
        )
        assert resp.status_code == 400
        assert "5 fields" in resp.get_json()["message"]

    def test_create_schedule_unknown_exchange(self, client) -> None:
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "30 9 * * 1-5", "exchange": "INVALID"},
        )
        assert resp.status_code == 400
        assert "Unsupported exchange" in resp.get_json()["message"]

    def test_create_schedule_unknown_strategy(self, client, flask_app) -> None:
        flask_app.config["STRATEGY_RUNNER"].get_status.side_effect = FileNotFoundError("not found")
        resp = client.post(
            "/api/v1/strategies/ghost-id/schedule",
            json={"cron": "30 9 * * 1-5"},
        )
        assert resp.status_code == 404
        # Reset side effect
        flask_app.config["STRATEGY_RUNNER"].get_status.side_effect = None
        flask_app.config["STRATEGY_RUNNER"].get_status.return_value = {"state": "stopped"}

    def test_create_schedule_no_cron_scheduler(self, client, flask_app) -> None:
        flask_app.config["CRON_SCHEDULER"] = None
        resp = client.post(
            "/api/v1/strategies/strat-001/schedule",
            json={"cron": "30 9 * * 1-5"},
        )
        assert resp.status_code == 503
        flask_app.config["CRON_SCHEDULER"] = _make_scheduler()

    # --- DELETE /<id>/schedule ---

    def test_delete_schedule_success(self, client, flask_app) -> None:
        # First create
        flask_app.config["CRON_SCHEDULER"].schedule(
            "strat-001", "30 9 * * 1-5", lambda: None
        )
        resp = client.delete("/api/v1/strategies/strat-001/schedule")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_delete_schedule_not_found(self, client) -> None:
        resp = client.delete("/api/v1/strategies/no-schedule/schedule")
        assert resp.status_code == 404

    # --- GET /scheduled ---

    def test_list_scheduled_empty(self, client, flask_app) -> None:
        # Ensure no schedules exist
        flask_app.config["CRON_SCHEDULER"] = _make_scheduler()
        resp = client.get("/api/v1/strategies/scheduled")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["schedules"] == []

    def test_list_scheduled_returns_entry(self, client, flask_app) -> None:
        flask_app.config["CRON_SCHEDULER"] = _make_scheduler()
        flask_app.config["CRON_SCHEDULER"].schedule(
            "strat-001", "30 9 * * 1-5", lambda: None, exchange="NSE"
        )
        resp = client.get("/api/v1/strategies/scheduled")
        assert resp.status_code == 200
        schedules = resp.get_json()["data"]["schedules"]
        assert len(schedules) == 1
        entry = schedules[0]
        assert entry["strategy_id"] == "strat-001"
        assert entry["cron"] == "30 9 * * 1-5"
        assert entry["exchange"] == "NSE"

    def test_list_scheduled_normalises_key_to_cron(self, client, flask_app) -> None:
        """Response must use 'cron' key, not 'cron_expr'."""
        flask_app.config["CRON_SCHEDULER"] = _make_scheduler()
        flask_app.config["CRON_SCHEDULER"].schedule(
            "strat-002", "0 15 * * 1-5", lambda: None
        )
        resp = client.get("/api/v1/strategies/scheduled")
        entry = resp.get_json()["data"]["schedules"][0]
        assert "cron" in entry
        assert "cron_expr" not in entry

    def test_list_scheduled_no_scheduler(self, client, flask_app) -> None:
        flask_app.config["CRON_SCHEDULER"] = None
        resp = client.get("/api/v1/strategies/scheduled")
        assert resp.status_code == 503
        flask_app.config["CRON_SCHEDULER"] = _make_scheduler()
