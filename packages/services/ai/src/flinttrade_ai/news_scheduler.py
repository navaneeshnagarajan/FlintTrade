"""Scheduled news polling for FlintTrade AI.

Adapted from FinSights/app/services/scheduler.py:
- APScheduler-style async scheduling pattern (re-implemented with asyncio)
- Job registry with enable/disable toggle
- TTL-based deduplication cache

Polling schedule (IST, Asia/Kolkata):
    - 07:00       Pre-market poll — all three RSS sources
    - 09:15–15:30 Intraday polls every 15 minutes (market hours)
    - 16:30       Post-market summary poll

The scheduler is entirely asyncio-based — no threads, no APScheduler
dependency. A single ``asyncio.Task`` runs a continuous loop that wakes up
at each scheduled time.

Integration with NewsScraper:
    NewsScheduler wraps the existing NewsScraper from news_scraper.py.
    All fetched articles are deduplicated by title via an in-memory TTL cache.

Event emission:
    After each successful poll, registered async callbacks are called with a
    ``NewsEvent`` payload. The FlintTrade backend can wire these callbacks to
    WebSocket broadcasts or Jotai atom updates.

Usage::

    from flinttrade_ai.news_scheduler import NewsScheduler

    scheduler = NewsScheduler()
    scheduler.on_news(my_async_callback)   # async def callback(event: NewsEvent)
    await scheduler.start()
    # ... runs in background ...
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger("flinttrade.ai.news_scheduler")

# IST offset
_IST = timezone(timedelta(hours=5, minutes=30))

# Market hours in IST (hour, minute) tuples
_MARKET_OPEN = (9, 15)
_MARKET_CLOSE = (15, 30)

# Intraday poll interval (minutes)
_INTRADAY_INTERVAL_MIN = 15

# Default TTL for deduplication cache entries (seconds)
_DEFAULT_CACHE_TTL = 3600.0

# Type alias for event callback
NewsEventCallback = Callable[["NewsEvent"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PollType(str, Enum):
    """Classification of a news polling run."""

    PRE_MARKET = "pre_market"
    INTRADAY = "intraday"
    POST_MARKET = "post_market"
    MANUAL = "manual"


class NewsEvent(BaseModel):
    """Payload emitted after a successful news poll.

    Attributes:
        poll_type: Which scheduled slot triggered the poll.
        articles_fetched: Total articles retrieved in this run.
        new_articles: Articles not seen in the deduplication cache.
        timestamp: UTC time of the poll.
        sources: List of source keys that were queried.
    """

    poll_type: PollType
    articles_fetched: int
    new_articles: list[dict[str, str]]
    timestamp: datetime
    sources: list[str]

    model_config = {"arbitrary_types_allowed": True}


class ScheduledJob(BaseModel):
    """A single scheduled polling job.

    Attributes:
        name: Unique job identifier.
        poll_type: PollType for categorisation.
        enabled: Whether the job fires during normal operation.
    """

    name: str
    poll_type: PollType
    enabled: bool = True


# ---------------------------------------------------------------------------
# TTL deduplication cache
# ---------------------------------------------------------------------------


class _NewsCache:
    """Simple in-memory TTL cache keyed by article title.

    Entries expire after *ttl_seconds* seconds. ``is_new`` returns True the
    first time a title is seen; subsequent calls within the TTL return False.
    """

    def __init__(self, ttl_seconds: float = _DEFAULT_CACHE_TTL) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, float] = {}  # title -> insertion_time

    def is_new(self, title: str) -> bool:
        """Return True if the title has not been cached within the TTL.

        Args:
            title: Article title to check.

        Returns:
            True if unseen or expired; False if seen within the TTL.
        """
        now = time.monotonic()
        existing = self._store.get(title)
        if existing is not None and (now - existing) < self._ttl:
            return False
        self._store[title] = now
        return True

    def sweep(self) -> int:
        """Remove expired entries. Returns count removed.

        Returns:
            Number of entries deleted.
        """
        now = time.monotonic()
        expired = [k for k, ts in self._store.items() if (now - ts) >= self._ttl]
        for key in expired:
            del self._store[key]
        return len(expired)

    @property
    def size(self) -> int:
        """Number of entries currently in the cache."""
        return len(self._store)


# ---------------------------------------------------------------------------
# NewsScheduler
# ---------------------------------------------------------------------------


class NewsScheduler:
    """Asyncio-based news polling scheduler for FlintTrade AI.

    Manages three classes of polls — pre-market, intraday, and post-market —
    and deduplicates results against an in-memory TTL cache. Registered async
    callbacks are invoked after each poll with a NewsEvent payload.

    Args:
        scraper: NewsScraper instance. If None, a default NewsScraper is
            created internally.
        cache_ttl: TTL in seconds for the deduplication cache.
        intraday_interval_min: Intraday poll frequency in minutes.
    """

    def __init__(
        self,
        scraper: Any | None = None,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        intraday_interval_min: int = _INTRADAY_INTERVAL_MIN,
    ) -> None:
        if scraper is None:
            from .sentiment import NewsScraper  # lazy import

            scraper = NewsScraper()

        self._scraper = scraper
        self._cache = _NewsCache(ttl_seconds=cache_ttl)
        self._intraday_interval_min = intraday_interval_min
        self._callbacks: list[NewsEventCallback] = []
        self._task: asyncio.Task[None] | None = None
        self._running = False

        self._jobs: dict[str, ScheduledJob] = {
            "pre_market": ScheduledJob(name="pre_market", poll_type=PollType.PRE_MARKET),
            "intraday": ScheduledJob(name="intraday", poll_type=PollType.INTRADAY),
            "post_market": ScheduledJob(name="post_market", poll_type=PollType.POST_MARKET),
        }

        logger.info("NewsScheduler created (intraday_interval=%d min)", intraday_interval_min)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduling loop.

        The loop runs as an asyncio Task and wakes up at the next scheduled
        event time. Calling start() when already running is a no-op.
        """
        if self._running:
            logger.warning("NewsScheduler.start() called but already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="news_scheduler_loop")
        logger.info("NewsScheduler started")

    async def stop(self) -> None:
        """Stop the background loop and cancel the asyncio Task."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("NewsScheduler stopped")

    @property
    def is_running(self) -> bool:
        """True if the scheduler loop is active."""
        return self._running and self._task is not None and not self._task.done()

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def enable_job(self, job_name: str) -> None:
        """Enable a named job.

        Args:
            job_name: One of ``"pre_market"``, ``"intraday"``, ``"post_market"``.

        Raises:
            KeyError: If job_name is not recognised.
        """
        self._jobs[job_name].enabled = True
        logger.info("NewsScheduler: job '%s' enabled", job_name)

    def disable_job(self, job_name: str) -> None:
        """Disable a named job (it will be skipped when its slot fires).

        Args:
            job_name: Job name.

        Raises:
            KeyError: If job_name is not recognised.
        """
        self._jobs[job_name].enabled = False
        logger.info("NewsScheduler: job '%s' disabled", job_name)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Return the current list of jobs with their enabled state.

        Returns:
            List of dicts with keys ``name``, ``poll_type``, ``enabled``.
        """
        return [j.model_dump() for j in self._jobs.values()]

    # ------------------------------------------------------------------
    # Event callbacks
    # ------------------------------------------------------------------

    def on_news(self, callback: NewsEventCallback) -> None:
        """Register an async callback to be called after each poll.

        The callback signature must be: ``async def callback(event: NewsEvent) -> None``.

        Args:
            callback: Async callable accepting a NewsEvent.
        """
        self._callbacks.append(callback)

    # ------------------------------------------------------------------
    # Manual poll
    # ------------------------------------------------------------------

    async def poll_now(
        self,
        sources: list[str] | None = None,
        poll_type: PollType = PollType.MANUAL,
    ) -> NewsEvent:
        """Trigger an immediate poll outside the normal schedule.

        Args:
            sources: Source keys to poll. Defaults to all three RSS sources.
            poll_type: Override poll type label in the emitted event.

        Returns:
            NewsEvent describing the results.
        """
        if sources is None:
            from .sentiment import RSS_SOURCES  # lazy

            sources = list(RSS_SOURCES.keys())
        return await self._run_poll(poll_type, sources)

    # ------------------------------------------------------------------
    # Internal scheduler loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main scheduling loop. Wakes at the next scheduled IST time."""
        while self._running:
            now_ist = datetime.now(_IST)
            next_fire, poll_type, job_name = self._next_event(now_ist)
            sleep_secs = max(0.0, (next_fire - now_ist).total_seconds())

            logger.debug(
                "NewsScheduler: next event=%s (%s) in %.0fs",
                poll_type.value,
                next_fire.isoformat(),
                sleep_secs,
            )

            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                return

            if not self._running:
                return

            job = self._jobs.get(job_name)
            if job is None or not job.enabled:
                continue

            from .sentiment import RSS_SOURCES  # lazy

            await self._run_poll(poll_type, list(RSS_SOURCES.keys()))

    def _next_event(self, now: datetime) -> tuple[datetime, PollType, str]:
        """Compute the next scheduled event relative to *now* (IST).

        Schedule:
        - 07:00 IST → PRE_MARKET
        - 09:15–15:30 IST every N minutes → INTRADAY
        - 16:30 IST → POST_MARKET

        Args:
            now: Current IST datetime.

        Returns:
            Tuple of (fire_datetime_IST, PollType, job_name).
        """
        candidates: list[tuple[datetime, PollType, str]] = []
        today = now.date()

        # Pre-market: today 07:00
        pre = datetime(today.year, today.month, today.day, 7, 0, tzinfo=_IST)
        if pre > now:
            candidates.append((pre, PollType.PRE_MARKET, "pre_market"))
        else:
            # Tomorrow 07:00
            tomorrow = today + timedelta(days=1)
            pre_tmrw = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 7, 0, tzinfo=_IST)
            candidates.append((pre_tmrw, PollType.PRE_MARKET, "pre_market"))

        # Post-market: today 16:30
        post = datetime(today.year, today.month, today.day, 16, 30, tzinfo=_IST)
        if post > now:
            candidates.append((post, PollType.POST_MARKET, "post_market"))
        else:
            tomorrow = today + timedelta(days=1)
            post_tmrw = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 16, 30, tzinfo=_IST)
            candidates.append((post_tmrw, PollType.POST_MARKET, "post_market"))

        # Intraday: next N-minute slot within market hours
        market_open_dt = datetime(today.year, today.month, today.day, _MARKET_OPEN[0], _MARKET_OPEN[1], tzinfo=_IST)
        market_close_dt = datetime(today.year, today.month, today.day, _MARKET_CLOSE[0], _MARKET_CLOSE[1], tzinfo=_IST)

        if market_open_dt <= now <= market_close_dt:
            # We are inside market hours — next slot from now
            elapsed_min = (now - market_open_dt).total_seconds() / 60
            slots_passed = int(elapsed_min // self._intraday_interval_min) + 1
            next_slot = market_open_dt + timedelta(minutes=slots_passed * self._intraday_interval_min)
            if next_slot <= market_close_dt:
                candidates.append((next_slot, PollType.INTRADAY, "intraday"))
        elif now < market_open_dt:
            # Before market open today
            candidates.append((market_open_dt, PollType.INTRADAY, "intraday"))
        else:
            # After close — schedule for tomorrow's open
            tomorrow = today + timedelta(days=1)
            next_open = datetime(
                tomorrow.year, tomorrow.month, tomorrow.day, _MARKET_OPEN[0], _MARKET_OPEN[1], tzinfo=_IST
            )
            candidates.append((next_open, PollType.INTRADAY, "intraday"))

        # Return the soonest candidate
        candidates.sort(key=lambda t: t[0])
        return candidates[0]

    # ------------------------------------------------------------------
    # Poll execution
    # ------------------------------------------------------------------

    async def _run_poll(self, poll_type: PollType, sources: list[str]) -> NewsEvent:
        """Execute a poll, deduplicate results, emit callbacks.

        Args:
            poll_type: Classification of this poll run.
            sources: List of RSS source keys to query.

        Returns:
            NewsEvent summarising the run.
        """
        all_articles: list[Any] = []
        new_articles: list[dict[str, str]] = []

        for source in sources:
            try:
                fetched = await asyncio.get_event_loop().run_in_executor(None, self._scraper.fetch_headlines, source)
                all_articles.extend(fetched)
            except Exception as exc:
                logger.warning("NewsScheduler: error fetching %s — %s", source, exc)

        for article in all_articles:
            if self._cache.is_new(article.title):
                new_articles.append(article.to_dict())

        # Sweep expired cache entries periodically (every 100 new articles seen)
        if self._cache.size > 100:
            self._cache.sweep()

        event = NewsEvent(
            poll_type=poll_type,
            articles_fetched=len(all_articles),
            new_articles=new_articles,
            timestamp=datetime.now(timezone.utc),
            sources=sources,
        )

        logger.info(
            "NewsScheduler poll: type=%s fetched=%d new=%d",
            poll_type.value,
            event.articles_fetched,
            len(new_articles),
        )

        await self._emit(event)
        return event

    async def _emit(self, event: NewsEvent) -> None:
        """Call all registered async callbacks with the event.

        Callbacks that raise exceptions are logged and skipped.

        Args:
            event: The NewsEvent to dispatch.
        """
        for callback in self._callbacks:
            try:
                await callback(event)
            except Exception as exc:
                logger.error("NewsScheduler callback error: %s", exc)
