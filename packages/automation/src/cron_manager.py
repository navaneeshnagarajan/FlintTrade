"""Scheduled task manager using APScheduler.

Built-in jobs:
1. health_check_job: 9:10 AM IST (verify OpenAlgo session)
2. square_off_warning_job: 3:20 PM IST (warn before square-off)
3. eod_logout_job: 11:45 PM IST (SEBI session logout)
4. holiday_check: on startup (load holidays from OpenAlgo)

Additional optional jobs:
5. backup: 12:00 AM daily
6. post_market_analysis: 3:45 PM IST
7. mcx_close_check: 11:55 PM IST

Note: Broker login (TOTP) is NOT handled by FlintTrade.
OpenAlgo manages broker authentication. See packages/automation/src/totp_login.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger("flinttrade.automation.cron")

IST = timezone(timedelta(hours=5, minutes=30))


class JobStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"


@dataclass
class JobHistory:
    """Record of a single job execution."""

    job_name: str
    started_at: str
    finished_at: str = ""
    success: bool = False
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class JobDefinition:
    """A registered scheduled job."""

    name: str
    description: str = ""
    handler: Callable[[], Any] | None = None
    trigger_type: str = "cron"       # "cron", "interval"
    trigger_args: dict[str, Any] = field(default_factory=dict)
    status: str = "ACTIVE"
    last_run: str = ""
    last_success: bool = False
    run_count: int = 0
    error_count: int = 0
    history: list[JobHistory] = field(default_factory=list)
    max_history: int = 50


# Default job schedule definitions
DEFAULT_JOBS: dict[str, dict[str, Any]] = {
    "health_check_job": {
        "description": "Verify OpenAlgo session at 9:10 AM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 9, "minute": 10, "day_of_week": "mon-fri", "timezone": "Asia/Kolkata"},
    },
    "square_off_warning_job": {
        "description": "Square-off warning at 3:20 PM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 15, "minute": 20, "day_of_week": "mon-fri", "timezone": "Asia/Kolkata"},
    },
    "eod_logout_job": {
        "description": "SEBI end-of-day session logout at 11:45 PM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 23, "minute": 45, "day_of_week": "mon-fri", "timezone": "Asia/Kolkata"},
    },
    "health_check": {
        "description": "Check OpenAlgo/WebSocket health every 5 minutes during market hours",
        "trigger_type": "interval",
        "trigger_args": {"minutes": 5},
    },
    "backup": {
        "description": "Daily backup of DuckDB, configs, audit logs at midnight",
        "trigger_type": "cron",
        "trigger_args": {"hour": 0, "minute": 0, "timezone": "Asia/Kolkata"},
    },
    "post_market_analysis": {
        "description": "Post-market analysis at 3:45 PM IST after equity close",
        "trigger_type": "cron",
        "trigger_args": {"hour": 15, "minute": 45, "timezone": "Asia/Kolkata"},
    },
    "mcx_close_check": {
        "description": "MCX close position check at 11:55 PM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 23, "minute": 55, "timezone": "Asia/Kolkata"},
    },
}


# ---------------------------------------------------------------------------
# Built-in job implementations
# ---------------------------------------------------------------------------


def _is_market_holiday(holidays: set[str] | None = None) -> bool:
    """Check if today is a market holiday."""
    today = datetime.now(IST).date()
    if today.weekday() >= 5:
        return True
    if holidays and today.isoformat() in holidays:
        return True
    return False


def make_health_check_job(
    openalgo_client: Any,
    audit_logger: Any = None,
    telegram_bot: Any = None,
    holidays: set[str] | None = None,
) -> Callable[[], None]:
    """Create the health_check_job handler."""

    def health_check_job() -> None:
        if _is_market_holiday(holidays):
            return
        success = False
        error = ""
        try:
            import asyncio
            result = asyncio.run(openalgo_client.ping())
            success = result.get("status") == "success" if isinstance(result, dict) else False
        except Exception as exc:
            error = str(exc)
            logger.error("health_check_job: ping failed — %s", exc)

        if audit_logger:
            audit_logger.log_event(
                "HEALTH_CHECK",
                success=success,
                error=error,
            )

        if not success and telegram_bot:
            telegram_bot.send_message(
                f"🔴 *Health Check Failed*\nOpenAlgo ping failed at "
                f"{datetime.now(IST).strftime('%H:%M IST')}\nError: {error or 'no response'}"
            )

    return health_check_job


def make_square_off_warning_job(
    telegram_bot: Any = None,
    holidays: set[str] | None = None,
) -> Callable[[], None]:
    """Create the square_off_warning_job handler."""

    def square_off_warning_job() -> None:
        if _is_market_holiday(holidays):
            return
        msg = "⚠️ 10 minutes to square off open positions"
        logger.warning(msg)
        if telegram_bot:
            telegram_bot.send_message(msg)

    return square_off_warning_job


def make_eod_logout_job(
    audit_logger: Any = None,
    holidays: set[str] | None = None,
) -> Callable[[], None]:
    """Create the eod_logout_job handler (SEBI requirement)."""

    def eod_logout_job() -> None:
        if _is_market_holiday(holidays):
            return
        logger.info("eod_logout_job: SEBI end-of-day session logout")
        if audit_logger:
            audit_logger.log_event(
                "SESSION_LOGOUT",
                source="cron",
                reason="SEBI end-of-day requirement",
            )

    return eod_logout_job


async def load_holidays_from_client(openalgo_client: Any) -> set[str]:
    """Load market holidays from OpenAlgo API. Must be awaited.

    OpenAlgo's /holidays endpoint can return an HTTP 200 with an empty body
    before a broker has authenticated.  That would trigger a
    ``json.JSONDecodeError`` inside the client's ``resp.json()`` call.  We
    treat that case separately so the log stays quiet and does not look
    like a real error.
    """
    import json as _json  # noqa: PLC0415

    try:
        data = await openalgo_client.holidays()
        holidays_list = data.get("holidays", []) if isinstance(data, dict) else []
        if isinstance(holidays_list, list):
            result = set(holidays_list)
            logger.info("Loaded %d market holidays", len(result))
            return result
    except (_json.JSONDecodeError, ValueError) as exc:
        # Empty body from OpenAlgo means "no broker yet authenticated".
        # Log once at INFO so it's traceable but not alarming.
        msg = str(exc)
        if "Expecting value" in msg or "line 1 column 1" in msg or not msg:
            logger.info(
                "Holidays endpoint returned no data (broker not yet "
                "authenticated) — continuing with empty list"
            )
        else:
            logger.warning("Failed to load holidays: %s", exc)
    except Exception as exc:
        logger.warning("Failed to load holidays: %s", exc)
    return set()


# ---------------------------------------------------------------------------
# CronManager
# ---------------------------------------------------------------------------


class CronManager:
    """Manage scheduled jobs using APScheduler.

    Usage::

        cron = CronManager(
            openalgo_client=client,
            audit_logger=auditor,
            telegram_bot=bot,
            totp_login=totp,
        )
        cron.register_builtin_jobs()
        cron.start()
    """

    def __init__(
        self,
        openalgo_client: Any = None,
        audit_logger: Any = None,
        telegram_bot: Any = None,
        totp_login: Any = None,
    ) -> None:
        self._jobs: dict[str, JobDefinition] = {}
        self._scheduler = None
        self._running = False
        self.openalgo_client = openalgo_client
        self.audit_logger = audit_logger
        self.telegram_bot = telegram_bot
        self.totp_login = totp_login
        self._holidays: set[str] = set()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def holidays(self) -> set[str]:
        return self._holidays

    def _get_scheduler(self) -> Any:
        """Lazy-initialise APScheduler."""
        if self._scheduler is not None:
            return self._scheduler

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()
            return self._scheduler
        except ImportError:
            raise ImportError("apscheduler required — pip install apscheduler")

    # ------------------------------------------------------------------
    # Built-in job registration
    # ------------------------------------------------------------------

    async def load_holidays(self) -> set[str]:
        """Load holidays from OpenAlgo and cache them. Must be awaited."""
        if self.openalgo_client:
            self._holidays = await load_holidays_from_client(self.openalgo_client)
        return self._holidays

    def register_builtin_jobs(self) -> None:
        """Register built-in jobs with their handlers."""
        if self.openalgo_client:
            self.register(
                "health_check_job",
                handler=make_health_check_job(
                    self.openalgo_client, self.audit_logger, self.telegram_bot, self._holidays,
                ),
                **DEFAULT_JOBS["health_check_job"],
            )

        self.register(
            "square_off_warning_job",
            handler=make_square_off_warning_job(self.telegram_bot, self._holidays),
            **DEFAULT_JOBS["square_off_warning_job"],
        )

        self.register(
            "eod_logout_job",
            handler=make_eod_logout_job(self.audit_logger, self._holidays),
            **DEFAULT_JOBS["eod_logout_job"],
        )

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: Callable[[], Any] | None = None,
        description: str = "",
        trigger_type: str = "cron",
        trigger_args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Register a new scheduled job."""
        defaults = DEFAULT_JOBS.get(name, {})
        job = JobDefinition(
            name=name,
            description=description or defaults.get("description", ""),
            handler=handler,
            trigger_type=trigger_type or defaults.get("trigger_type", "cron"),
            trigger_args=trigger_args or defaults.get("trigger_args", {}),
        )
        self._jobs[name] = job
        logger.info("Registered job: %s (%s)", name, job.trigger_type)

    def register_defaults(self, handlers: dict[str, Callable[[], Any]]) -> None:
        """Register all default jobs that have matching handlers."""
        for name, config in DEFAULT_JOBS.items():
            handler = handlers.get(name)
            if handler:
                self.register(
                    name=name,
                    handler=handler,
                    description=config["description"],
                    trigger_type=config["trigger_type"],
                    trigger_args=config["trigger_args"],
                )

    def unregister(self, name: str) -> None:
        """Remove a job from the registry."""
        self._jobs.pop(name, None)
        if self._scheduler and self._running:
            try:
                self._scheduler.remove_job(name)
            except Exception:
                logger.exception("Failed to remove cron job %s from scheduler", name)

    # ------------------------------------------------------------------
    # Job control
    # ------------------------------------------------------------------

    def enable(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.ACTIVE.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.resume_job(name)
                except Exception:
                    logger.exception("Failed to resume cron job %s", name)

    def disable(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.DISABLED.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.pause_job(name)
                except Exception:
                    logger.exception("Failed to pause cron job %s", name)

    def pause(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.PAUSED.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.pause_job(name)
                except Exception:
                    logger.exception("Failed to pause cron job %s", name)

    def resume(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.ACTIVE.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.resume_job(name)
                except Exception:
                    logger.exception("Failed to resume cron job %s", name)

    # ------------------------------------------------------------------
    # Job info
    # ------------------------------------------------------------------

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all registered jobs with status."""
        return [
            {
                "name": j.name,
                "description": j.description,
                "trigger_type": j.trigger_type,
                "status": j.status,
                "last_run": j.last_run,
                "last_success": j.last_success,
                "run_count": j.run_count,
                "error_count": j.error_count,
            }
            for j in self._jobs.values()
        ]

    def get_history(self, name: str) -> list[JobHistory]:
        """Get execution history for a specific job."""
        job = self._jobs.get(name)
        return list(job.history) if job else []

    # ------------------------------------------------------------------
    # Execution wrapper
    # ------------------------------------------------------------------

    def _run_job(self, name: str) -> None:
        """Execute a job with timing and error tracking."""
        job = self._jobs.get(name)
        if not job or not job.handler:
            return

        if job.status != JobStatus.ACTIVE.value:
            return

        start = time.monotonic()
        started_at = datetime.now(IST).isoformat()
        success = False
        error = ""

        try:
            job.handler()
            success = True
        except Exception as exc:
            error = str(exc)
            job.error_count += 1
            logger.error("Job '%s' failed: %s", name, exc)

        duration = time.monotonic() - start
        finished_at = datetime.now(IST).isoformat()

        job.run_count += 1
        job.last_run = finished_at
        job.last_success = success

        entry = JobHistory(
            job_name=name,
            started_at=started_at,
            finished_at=finished_at,
            success=success,
            duration_seconds=round(duration, 3),
            error=error,
        )
        job.history.append(entry)
        if len(job.history) > job.max_history:
            job.history = job.history[-job.max_history:]

        if success:
            logger.info("Job '%s' completed in %.1fs", name, duration)

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler (non-blocking background thread)."""
        scheduler = self._get_scheduler()

        for name, job in self._jobs.items():
            if not job.handler:
                continue

            trigger = job.trigger_type
            kwargs = dict(job.trigger_args)

            if trigger == "cron":
                scheduler.add_job(
                    self._run_job, "cron", args=[name],
                    id=name, **kwargs, replace_existing=True,
                )
            elif trigger == "interval":
                scheduler.add_job(
                    self._run_job, "interval", args=[name],
                    id=name, **kwargs, replace_existing=True,
                )

        scheduler.start()
        self._running = True
        logger.info("CronManager started with %d jobs", len(self._jobs))

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=False)
            self._running = False
            logger.info("CronManager stopped")

    def run_now(self, name: str) -> None:
        """Manually trigger a job immediately."""
        self._run_job(name)
