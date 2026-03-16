"""Scheduled task manager using APScheduler.

Built-in jobs:
1. totp_login: 8:30 AM IST daily (skip holidays)
2. health_check: every 5 minutes during market hours
3. backup: 12:00 AM daily
4. post_market_analysis: 3:45 PM IST (after equity close)
5. mcx_close_check: 11:55 PM IST (after MCX close)
6. ddns_update: every 10 seconds (IP change detection)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("flinttrade.automation.cron")

IST = timezone(timedelta(hours=5, minutes=30))


class JobStatus(str, Enum):
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
    "totp_login": {
        "description": "Daily TOTP broker login at 8:30 AM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 8, "minute": 30, "timezone": "Asia/Kolkata"},
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
    "ddns_update": {
        "description": "DDNS IP change detection every 10 seconds",
        "trigger_type": "interval",
        "trigger_args": {"seconds": 10},
    },
}


class CronManager:
    """Manage scheduled jobs using APScheduler.

    Usage::

        cron = CronManager()
        cron.register("totp_login", handler=my_totp_fn, trigger_type="cron",
                       trigger_args={"hour": 8, "minute": 30})
        cron.start()  # non-blocking
        cron.pause("health_check")
        cron.resume("health_check")
        cron.stop()
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobDefinition] = {}
        self._scheduler = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def _get_scheduler(self) -> Any:
        """Lazy-initialize APScheduler."""
        if self._scheduler is not None:
            return self._scheduler

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()
            return self._scheduler
        except ImportError:
            raise ImportError("apscheduler required — pip install apscheduler")

    # ------------------------------------------------------------------
    # Job registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: Callable[[], Any],
        description: str = "",
        trigger_type: str = "cron",
        trigger_args: dict[str, Any] | None = None,
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
                pass

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
                    pass

    def disable(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.DISABLED.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.pause_job(name)
                except Exception:
                    pass

    def pause(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.PAUSED.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.pause_job(name)
                except Exception:
                    pass

    def resume(self, name: str) -> None:
        job = self._jobs.get(name)
        if job:
            job.status = JobStatus.ACTIVE.value
            if self._running and self._scheduler:
                try:
                    self._scheduler.resume_job(name)
                except Exception:
                    pass

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
