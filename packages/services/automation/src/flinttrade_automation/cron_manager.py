"""Scheduled task manager using APScheduler.

Built-in jobs:
1. health_check_job: 9:10 AM IST (verify OpenAlgo session)
2. square_off_warning_job: 3:20 PM IST (warn before square-off)
3. eod_logout_job: 11:45 PM IST (SEBI session logout)
4. holiday_check: on startup (load holidays from OpenAlgo)
5. post_market_analysis: 3:45 PM IST (daily trade report; lazy trade-store
   resolve, Telegram summary, optional DuckDB persistence)

Additional optional jobs:
6. backup: 12:00 AM daily
7. mcx_close_check: 11:55 PM IST

Note: Broker login (TOTP) is NOT handled by FlintTrade.
OpenAlgo manages broker authentication. See packages/services/automation/src/totp_login.py.
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
    "db_optimise_job": {
        "description": "Nightly DuckDB CHECKPOINT + ANALYZE at 12:30 AM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 0, "minute": 30, "timezone": "Asia/Kolkata"},
    },
    "tick_retention_job": {
        "description": "Prune ticks older than the retention window at 12:45 AM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 0, "minute": 45, "timezone": "Asia/Kolkata"},
    },
    "overnight_optimise_job": {
        "description": "Overnight strategy optimisation at 2:00 AM IST (after EOD)",
        "trigger_type": "cron",
        "trigger_args": {"hour": 2, "minute": 0, "day_of_week": "mon-fri", "timezone": "Asia/Kolkata"},
    },
    "eod_sync_job": {
        "description": "EOD historical-data delta sync at 6:30 PM IST (after close)",
        "trigger_type": "cron",
        "trigger_args": {"hour": 18, "minute": 30, "day_of_week": "mon-fri", "timezone": "Asia/Kolkata"},
    },
    "webhook_nonce_gc_job": {
        "description": "Prune expired webhook replay nonces at 3:00 AM IST",
        "trigger_type": "cron",
        "trigger_args": {"hour": 3, "minute": 0, "timezone": "Asia/Kolkata"},
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
            # One-owner-loop rule: never drive the shared client on a fresh
            # asyncio.run() loop (poisons its pooled httpx connections).
            from flinttrade_core.openalgo_client import client_call_sync  # noqa: PLC0415

            result = client_call_sync(openalgo_client, openalgo_client.ping())
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


def make_db_optimise_job(
    storage: Any = None,
    storage_lock: Any = None,
    *,
    extra_stores: Callable[[], Any] | None = None,
) -> Callable[[], None]:
    """Create the db_optimise_job handler — nightly DuckDB maintenance.

    Runs ``CHECKPOINT`` (folds the write-ahead log back into the main database
    file, reclaiming space) and ``ANALYZE`` (refreshes the optimiser's column
    statistics) on EVERY configured store — the trade journal AND the live tick
    store — so analytical queries stay fast and neither file grows unbounded as
    ticks and trades accumulate.

    Each store is maintained under its own lock — DuckDB allows only one
    read-write connection per file and its connections are not thread-safe, so
    the lock serialises against the store's live writer (e.g. the TickRecorder on
    the async loop). Runs every day (maintenance is not market-gated).
    Best-effort: a per-store failure is logged and the next store still runs.

    Args:
        storage: The shared trade ``StorageManager`` (or ``None`` to skip).
        storage_lock: A lock serialising access to ``storage``'s connection.
        extra_stores: Optional zero-arg provider returning an iterable of
            ``(storage, lock, label)`` tuples, resolved at FIRE time (so stores
            wired after registration — e.g. the tick store — are picked up).
    """

    def db_optimise_job() -> None:
        targets: list[tuple[Any, Any, str, bool]] = []
        if storage is not None:
            targets.append((storage, storage_lock, "trade", False))
        if extra_stores is not None:
            try:
                targets.extend(
                    (s, lk, lbl, True) for s, lk, lbl in extra_stores() if s is not None
                )
            except Exception as exc:  # a bad provider must not abort maintenance
                logger.error("db_optimise_job: extra-store provider failed — %s", exc)

        if not targets:
            logger.warning("db_optimise_job: no store configured; skipping")
            return

        def dynamic_store_is_current(store: Any, lock: Any, label: str) -> bool:
            if extra_stores is None:
                return False
            try:
                return any(
                    current_store is store
                    and current_lock is lock
                    and current_label == label
                    for current_store, current_lock, current_label in extra_stores()
                )
            except Exception as exc:
                logger.error("db_optimise_job: extra-store revalidation failed — %s", exc)
                return False

        for store, lock, label, dynamic in targets:
            try:
                if lock is not None:
                    with lock:
                        if dynamic and not dynamic_store_is_current(store, lock, label):
                            continue
                        store.connection.execute("CHECKPOINT")
                        store.connection.execute("ANALYZE")
                else:
                    if dynamic and not dynamic_store_is_current(store, lock, label):
                        continue
                    store.connection.execute("CHECKPOINT")
                    store.connection.execute("ANALYZE")
                logger.info("db_optimise_job: %s store CHECKPOINT + ANALYZE complete", label)
            except Exception as exc:
                logger.error("db_optimise_job: %s store maintenance failed — %s", label, exc)

    return db_optimise_job


def make_tick_retention_job(provider: Callable[[], Any]) -> Callable[[], None]:
    """Create the tick_retention_job handler — nightly prune of the tick store.

    ``provider`` is resolved at FIRE time and returns ``(storage, lock, days)``
    so the tick store wired after registration is picked up. No-ops without a
    store or a positive retention window. Runs under the store's shared lock
    (the recorder writes the same DuckDB connection). Best-effort: any failure
    is logged, never raised.
    """

    def tick_retention_job() -> None:
        try:
            storage, lock, days = provider()
        except Exception as exc:  # a bad provider must not crash the scheduler
            logger.error("tick_retention_job: provider failed — %s", exc)
            return
        if storage is None or days <= 0:
            return

        def current_retention_days() -> int | None:
            try:
                current_storage, current_lock, current_days = provider()
            except Exception as exc:
                logger.error("tick_retention_job: provider revalidation failed — %s", exc)
                return None
            if current_storage is not storage or current_lock is not lock:
                return None
            return int(current_days) if current_days > 0 else None

        try:
            if lock is not None:
                with lock:
                    active_days = current_retention_days()
                    if active_days is None:
                        return
                    removed = storage.prune_ticks(active_days)
            else:
                active_days = current_retention_days()
                if active_days is None:
                    return
                removed = storage.prune_ticks(active_days)
            logger.info("tick_retention_job: pruned %d ticks older than %d days", removed, active_days)
        except Exception as exc:
            logger.error("tick_retention_job: prune failed — %s", exc)

    return tick_retention_job


def make_webhook_nonce_gc_job(gc_nonces: Callable[[], int]) -> Callable[[], None]:
    """Create a best-effort maintenance handler for webhook replay evidence."""

    def webhook_nonce_gc_job() -> None:
        try:
            removed = gc_nonces()
        except Exception as exc:
            logger.error("webhook_nonce_gc_job: prune failed — %s", type(exc).__name__)
            return
        logger.info("webhook_nonce_gc_job: pruned %d expired nonces", removed)

    return webhook_nonce_gc_job


def make_eod_sync_job(
    starter: Callable[[], Any],
    holidays: set[str] | None = None,
) -> Callable[[], None]:
    """Create the eod_sync_job handler — daily historical-data delta sync.

    Fires after market close and calls the injected ``starter`` (the shared
    ``start_watchlist_download`` core — the SAME path the manual Settings
    button uses, so there is no parallel download implementation). Skips
    weekends/holidays; the underlying Historify engine handles delta/resume so
    re-syncing an already-current store is cheap.

    Args:
        starter: Zero-arg callable that starts the sync and returns the job
            snapshot (or None when the watchlist has nothing enabled).
        holidays: Market holiday dates (ISO strings) to skip.
    """

    def eod_sync_job() -> None:
        if _is_market_holiday(holidays):
            logger.info("eod_sync_job: market holiday — skipping")
            return
        try:
            job = starter()
        except Exception as exc:
            logger.error("eod_sync_job: sync start failed — %s", exc)
            return
        if job is None:
            logger.info("eod_sync_job: no enabled watchlist items — nothing to sync")
        else:
            logger.info("eod_sync_job: started delta sync job %s", getattr(job, "job_id", "?"))

    return eod_sync_job


def make_post_market_analysis_job(
    provider: Callable[[], tuple[Any, Any, str | None]],
    telegram_bot: Any = None,
    holidays: set[str] | None = None,
) -> Callable[[], None]:
    """Create the post_market_analysis handler — daily report at 3:45 PM IST.

    ``provider`` is resolved at FIRE time and returns ``(storage, lock,
    report_db)`` — the shared trade ``StorageManager``, the lock serialising
    access to its DuckDB connection, and an optional SEPARATE DuckDB file for
    persisted daily reports (never the trade store's own file — DuckDB allows
    only one read-write connection per file). Reads today's trades under the
    lock, runs :class:`flinttrade_automation.post_market.PostMarketAnalysis`
    (report build + optional persistence + Telegram summary), and never
    raises: a missing trade store logs-and-skips honestly and any failure is
    logged rather than crashing the scheduler.

    Args:
        provider: Zero-arg callable returning ``(storage, lock, report_db)``.
        telegram_bot: Optional Telegram bot for the daily summary message.
        holidays: Market holiday dates (ISO strings) to skip.
    """

    def post_market_analysis() -> None:
        if _is_market_holiday(holidays):
            logger.info("post_market_analysis: market holiday — skipping")
            return
        try:
            storage, lock, report_db = provider()
        except Exception as exc:  # a bad provider must not crash the scheduler
            logger.error("post_market_analysis: trade-store provider failed — %s", exc)
            return
        if storage is None:
            logger.info("post_market_analysis: no trade store configured — skipping")
            return

        today = datetime.now(IST).strftime("%Y-%m-%d")
        try:
            if lock is not None:
                with lock:
                    rows = storage.get_trades_by_date(today)
            else:
                rows = storage.get_trades_by_date(today)
        except Exception as exc:
            logger.error("post_market_analysis: could not read today's trades — %s", exc)
            return

        # Lazy import keeps APScheduler-only deployments light and mirrors the
        # other built-in handlers.
        from flinttrade_automation.post_market import PostMarketAnalysis, TradeEntry  # noqa: PLC0415

        try:
            trades = [
                TradeEntry(
                    symbol=str(row.get("symbol") or ""),
                    exchange=str(row.get("exchange") or ""),
                    action=str(row.get("action") or ""),
                    quantity=int(row.get("quantity") or 0),
                    entry_price=float(row.get("entry_price") or 0.0),
                    exit_price=float(row.get("exit_price") or 0.0),
                    pnl=float(row.get("pnl") or 0.0),
                    strategy=str(row.get("strategy") or ""),
                )
                for row in rows
            ]
            engine = PostMarketAnalysis(telegram_bot=telegram_bot, duckdb_path=report_db)
            report = engine.run(trades, report_date=today)
            logger.info(
                "post_market_analysis: report built for %s — %d trades, net P&L %+.0f",
                report.report_date,
                report.total_trades,
                report.net_pnl,
            )
        except Exception as exc:
            logger.error("post_market_analysis: report generation failed — %s", exc)

    return post_market_analysis


def make_overnight_optimise_job(optimiser: Callable[[], Any]) -> Callable[[], None]:
    """Create the overnight strategy-optimisation handler.

    Runs the injected ``optimiser`` callable (e.g. a hyperopt / auto-retrain
    sweep) once overnight, so "optimise overnight" is an actual scheduled trigger
    rather than a library that is never invoked. Errors are logged, never raised
    (a failed optimisation must not crash the scheduler).
    """

    def overnight_optimise_job() -> None:
        try:
            logger.info("overnight_optimise_job: starting overnight strategy optimisation")
            optimiser()
            logger.info("overnight_optimise_job: optimisation complete")
        except Exception as exc:  # noqa: BLE001 - never crash the scheduler
            logger.error("overnight_optimise_job: optimisation failed — %s", exc)

    return overnight_optimise_job


async def load_holidays_from_client(
    openalgo_client: Any,
    *,
    payload_sink: Callable[[Any], None] | None = None,
    year: int | None = None,
) -> set[str]:
    """Load market holidays from OpenAlgo API. Must be awaited.

    OpenAlgo's /holidays endpoint can return an HTTP 200 with an empty body
    before a broker has authenticated.  That would trigger a
    ``json.JSONDecodeError`` inside the client's ``resp.json()`` call.  We
    treat that case separately so the log stays quiet and does not look
    like a real error.
    """
    import json as _json  # noqa: PLC0415

    try:
        calendar_year = year if year is not None else datetime.now(IST).year
        data = await openalgo_client.holidays(
            year=str(calendar_year),
            allow_legacy_fallback=True,
        )
        from flinttrade_core.openalgo_client import (  # noqa: PLC0415
            is_authoritative_market_calendar,
            normalise_holiday_dates,
        )

        if not is_authoritative_market_calendar(data, expected_year=calendar_year):
            raise ValueError("market calendar response was not authoritative")

        result = set(normalise_holiday_dates(data, exchange="NSE"))
        if payload_sink is not None:
            payload_sink(data)
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
        # A 401/403 is the expected steady state with no broker authenticated
        # (Explore/no-broker mode). The refresh runs every few minutes, so
        # logging it at WARNING floods the log; keep it at INFO like the
        # empty-body case above and reserve WARNING for genuine failures.
        if getattr(exc, "status_code", None) in (401, 403):
            logger.info(
                "Market calendar unavailable — no broker authenticated yet; "
                "continuing with empty holiday list"
            )
        else:
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
        trade_storage: Any = None,
        trade_storage_lock: Any = None,
        webhook_nonce_gc: Callable[[], int] | None = None,
    ) -> None:
        self._jobs: dict[str, JobDefinition] = {}
        self._scheduler = None
        self._running = False
        self.openalgo_client = openalgo_client
        self.audit_logger = audit_logger
        self.telegram_bot = telegram_bot
        self.totp_login = totp_login
        # Shared trade/tick store + its lock, for the nightly DuckDB maintenance
        # job. May be set after construction (the store is created by the Flask
        # app factory, which runs after the CronManager is built).
        self.trade_storage = trade_storage
        self.trade_storage_lock = trade_storage_lock
        self.webhook_nonce_gc = webhook_nonce_gc
        # The live tick store (a SEPARATE DuckDB file written by TickRecorder on
        # the async loop) + the lock it shares with that recorder. Set after
        # construction, AFTER register_builtin_jobs runs — so the maintenance job
        # reads these lazily (at fire time), not at registration time.
        self.tick_storage = None
        self.tick_storage_lock = None
        # Days of ticks to keep; 0 disables pruning. Set after construction.
        self.tick_retention_days = 0
        # Optional SEPARATE DuckDB file for persisted post-market daily
        # reports (never the trade store's own file — one read-write
        # connection per DuckDB file). Set after construction; None keeps the
        # report log-and-Telegram only.
        self.post_market_report_db: str | None = None
        # Injected overnight strategy optimiser (a zero-arg callable). When set,
        # register_builtin_jobs schedules the "optimise overnight" trigger.
        self.overnight_optimiser: Callable[[], Any] | None = None
        # Injected EOD data-sync starter (zero-arg; the shared
        # start_watchlist_download core). Opt-in — set by the app factory only
        # when workspace.json data.auto_sync.enabled is true.
        self.eod_sync_starter: Callable[[], Any] | None = None
        self._holidays: set[str] = set()
        self._holiday_payload: Any | None = None
        self._holiday_generation = 0
        self._holiday_year: int | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def holidays(self) -> set[str]:
        return self._holidays

    @property
    def holiday_payload(self) -> Any | None:
        """Return the last raw calendar envelope for exchange-aware consumers."""
        return self._holiday_payload

    @property
    def holiday_generation(self) -> int:
        """Return the successful calendar-load generation."""
        return self._holiday_generation

    @property
    def holiday_year(self) -> int | None:
        """Return the requested year of the latest authoritative calendar."""
        return self._holiday_year

    def fail_closed_calendar_year(self, year: int) -> set[str]:
        """Treat every date in an unavailable calendar year as a holiday."""
        if year < 2020 or year > 2050:
            raise ValueError("calendar year must be between 2020 and 2050")
        current = datetime(year, 1, 1, tzinfo=IST)
        end = datetime(year + 1, 1, 1, tzinfo=IST)
        self._holidays.clear()
        while current < end:
            self._holidays.add(current.date().isoformat())
            current += timedelta(days=1)
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
            calendar_year = datetime.now(IST).year
            missing_payload = object()
            payload: Any = missing_payload

            def retain_payload(value: Any) -> None:
                nonlocal payload
                payload = value

            loaded = await load_holidays_from_client(
                self.openalgo_client,
                payload_sink=retain_payload,
                year=calendar_year,
            )
            if payload is missing_payload:
                return self._holidays
            self._holiday_payload = payload
            self._holiday_year = calendar_year
            self._holiday_generation += 1
            self._holidays.clear()
            self._holidays.update(loaded)
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

        # Nightly DuckDB maintenance — only when a trade store is wired. The tick
        # store is resolved lazily (it is created after this runs), so the job
        # maintains it too once it exists.
        if self.trade_storage is not None:
            self.register(
                "db_optimise_job",
                handler=make_db_optimise_job(
                    self.trade_storage,
                    self.trade_storage_lock,
                    extra_stores=lambda: [
                        (self.tick_storage, self.tick_storage_lock, "tick"),
                    ],
                ),
                **DEFAULT_JOBS["db_optimise_job"],
            )

        # Tick capture owns a separate store and may run without the trade
        # journal. Resolve it lazily so pruning is always scheduled, then no-ops
        # until capture publishes a store and positive retention window.
        self.register(
            "tick_retention_job",
            handler=make_tick_retention_job(
                lambda: (self.tick_storage, self.tick_storage_lock, self.tick_retention_days),
            ),
            **DEFAULT_JOBS["tick_retention_job"],
        )

        if self.webhook_nonce_gc is not None:
            self.register(
                "webhook_nonce_gc_job",
                handler=make_webhook_nonce_gc_job(self.webhook_nonce_gc),
                **DEFAULT_JOBS["webhook_nonce_gc_job"],
            )

        # Post-market daily report at 3:45 PM IST. The trade store is resolved
        # lazily (like tick_retention_job) so a store wired after registration
        # is still picked up; without one the handler logs-and-skips honestly.
        self.register(
            "post_market_analysis",
            handler=make_post_market_analysis_job(
                lambda: (self.trade_storage, self.trade_storage_lock, self.post_market_report_db),
                telegram_bot=self.telegram_bot,
                holidays=self._holidays,
            ),
            **DEFAULT_JOBS["post_market_analysis"],
        )

        # Overnight strategy optimisation — only when an optimiser is injected.
        if self.overnight_optimiser is not None:
            self.register(
                "overnight_optimise_job",
                handler=make_overnight_optimise_job(self.overnight_optimiser),
                **DEFAULT_JOBS["overnight_optimise_job"],
            )

        # EOD historical-data delta sync — only when the opt-in starter is
        # injected (workspace.json data.auto_sync.enabled).
        if self.eod_sync_starter is not None:
            self.register(
                "eod_sync_job",
                handler=make_eod_sync_job(self.eod_sync_starter, self._holidays),
                **DEFAULT_JOBS["eod_sync_job"],
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

    def schedule_once(
        self,
        name: str,
        *,
        handler: Callable[[], Any],
        run_at: datetime,
        description: str = "",
    ) -> None:
        """Register one timezone-aware date job, including after scheduler start."""
        if not isinstance(run_at, datetime) or run_at.tzinfo is None or run_at.utcoffset() is None:
            raise ValueError("run_at must be a timezone-aware datetime")
        previous = self._jobs.get(name)
        job = JobDefinition(
            name=name,
            description=description,
            handler=handler,
            trigger_type="date",
            trigger_args={"run_date": run_at},
        )
        self._jobs[name] = job
        if self._scheduler is not None and self._running:
            try:
                self._scheduler.add_job(
                    self._run_once_job,
                    "date",
                    args=[name],
                    id=name,
                    run_date=run_at,
                    replace_existing=True,
                )
            except Exception:
                if previous is None:
                    self._jobs.pop(name, None)
                else:
                    self._jobs[name] = previous
                raise
        logger.info("Registered one-shot job: %s at %s", name, run_at.isoformat())

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

    def _run_once_job(self, name: str) -> None:
        """Execute and retire one exact registered date-job generation."""
        job = self._jobs.get(name)
        try:
            self._run_job(name)
        finally:
            if self._jobs.get(name) is job:
                self._jobs.pop(name, None)

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
            elif trigger == "date":
                scheduler.add_job(
                    self._run_once_job, "date", args=[name],
                    id=name, **kwargs, replace_existing=True,
                )

        scheduler.start()
        self._running = True
        logger.info("CronManager started with %d jobs", len(self._jobs))

    def stop(self) -> None:
        """Stop the scheduler after every in-flight maintenance job finishes."""
        if self._scheduler and self._running:
            self._scheduler.shutdown(wait=True)
            self._running = False
            logger.info("CronManager stopped")

    def run_now(self, name: str) -> None:
        """Manually trigger a job immediately."""
        self._run_job(name)
