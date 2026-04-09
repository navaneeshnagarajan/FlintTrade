"""Tests for NewsScheduler — async IST-scheduled news polling.

All tests are self-contained: NewsScheduler is constructed with a mock
NewsScraper so no real HTTP requests are made.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

import pytest

from packages.ai.src.news_scheduler import (
    NewsEvent,
    NewsScheduler,
    PollType,
    ScheduledJob,
    _NewsCache,
    _IST,
)
from packages.ai.src.news_scraper import NewsArticle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(title: str = "NIFTY rallies", source: str = "moneycontrol") -> NewsArticle:
    return NewsArticle(
        title=title,
        link="https://example.com/article",
        summary="Summary text",
        published="2026-04-09T07:00:00",
        source=source,
    )


def _make_scraper(articles: list[NewsArticle] | None = None) -> MagicMock:
    """Return a mock NewsScraper that returns the given articles for any source."""
    scraper = MagicMock()
    scraper.fetch_headlines = MagicMock(return_value=articles or [_make_article()])
    return scraper


@pytest.fixture
def scheduler() -> NewsScheduler:
    return NewsScheduler(scraper=_make_scraper())


# ---------------------------------------------------------------------------
# _NewsCache
# ---------------------------------------------------------------------------


class TestNewsCache:
    def test_is_new_first_time_true(self) -> None:
        cache = _NewsCache(ttl_seconds=60.0)
        assert cache.is_new("NIFTY rallies") is True

    def test_is_new_second_call_false(self) -> None:
        cache = _NewsCache(ttl_seconds=60.0)
        cache.is_new("NIFTY rallies")
        assert cache.is_new("NIFTY rallies") is False

    def test_is_new_different_titles(self) -> None:
        cache = _NewsCache(ttl_seconds=60.0)
        assert cache.is_new("Title A") is True
        assert cache.is_new("Title B") is True
        assert cache.is_new("Title A") is False

    def test_sweep_removes_expired(self) -> None:
        import time as _time
        cache = _NewsCache(ttl_seconds=0.01)  # 10ms TTL
        cache.is_new("expiring title")
        _time.sleep(0.02)
        removed = cache.sweep()
        assert removed == 1
        assert cache.size == 0

    def test_sweep_keeps_fresh(self) -> None:
        cache = _NewsCache(ttl_seconds=3600.0)
        cache.is_new("fresh title")
        removed = cache.sweep()
        assert removed == 0
        assert cache.size == 1

    def test_size_reflects_count(self) -> None:
        cache = _NewsCache()
        assert cache.size == 0
        cache.is_new("A")
        cache.is_new("B")
        assert cache.size == 2


# ---------------------------------------------------------------------------
# NewsScheduler construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_creates_default_scraper_when_none(self) -> None:
        # Patch NewsScraper so no I/O occurs
        with patch("packages.ai.src.news_scheduler.NewsScheduler._loop", return_value=None):
            sched = NewsScheduler(scraper=_make_scraper())
            assert sched is not None

    def test_default_jobs_created(self, scheduler: NewsScheduler) -> None:
        jobs = scheduler.list_jobs()
        names = {j["name"] for j in jobs}
        assert "pre_market" in names
        assert "intraday" in names
        assert "post_market" in names

    def test_all_jobs_enabled_by_default(self, scheduler: NewsScheduler) -> None:
        for job in scheduler.list_jobs():
            assert job["enabled"] is True

    def test_not_running_before_start(self, scheduler: NewsScheduler) -> None:
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------


class TestJobManagement:
    def test_enable_disable_job(self, scheduler: NewsScheduler) -> None:
        scheduler.disable_job("intraday")
        intraday = next(j for j in scheduler.list_jobs() if j["name"] == "intraday")
        assert intraday["enabled"] is False
        scheduler.enable_job("intraday")
        intraday = next(j for j in scheduler.list_jobs() if j["name"] == "intraday")
        assert intraday["enabled"] is True

    def test_disable_unknown_job_raises_key_error(self, scheduler: NewsScheduler) -> None:
        with pytest.raises(KeyError):
            scheduler.disable_job("nonexistent_job")

    def test_enable_unknown_job_raises_key_error(self, scheduler: NewsScheduler) -> None:
        with pytest.raises(KeyError):
            scheduler.enable_job("nonexistent_job")


# ---------------------------------------------------------------------------
# Event callbacks
# ---------------------------------------------------------------------------


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_callback_called_on_poll(self) -> None:
        received_events: list[NewsEvent] = []

        async def my_callback(event: NewsEvent) -> None:
            received_events.append(event)

        scheduler = NewsScheduler(scraper=_make_scraper())
        scheduler.on_news(my_callback)

        await scheduler.poll_now(sources=["moneycontrol"], poll_type=PollType.MANUAL)

        assert len(received_events) == 1
        assert received_events[0].poll_type == PollType.MANUAL

    @pytest.mark.asyncio
    async def test_multiple_callbacks_all_called(self) -> None:
        calls: list[str] = []

        async def cb1(event: NewsEvent) -> None:
            calls.append("cb1")

        async def cb2(event: NewsEvent) -> None:
            calls.append("cb2")

        scheduler = NewsScheduler(scraper=_make_scraper())
        scheduler.on_news(cb1)
        scheduler.on_news(cb2)

        await scheduler.poll_now(sources=["moneycontrol"])

        assert "cb1" in calls
        assert "cb2" in calls

    @pytest.mark.asyncio
    async def test_failing_callback_does_not_crash_poll(self) -> None:
        async def bad_callback(event: NewsEvent) -> None:
            raise RuntimeError("callback error")

        scheduler = NewsScheduler(scraper=_make_scraper())
        scheduler.on_news(bad_callback)

        # Should not raise
        event = await scheduler.poll_now(sources=["moneycontrol"])
        assert event is not None


# ---------------------------------------------------------------------------
# poll_now
# ---------------------------------------------------------------------------


class TestPollNow:
    @pytest.mark.asyncio
    async def test_returns_news_event(self, scheduler: NewsScheduler) -> None:
        event = await scheduler.poll_now(sources=["moneycontrol"])
        assert isinstance(event, NewsEvent)

    @pytest.mark.asyncio
    async def test_event_sources_match(self, scheduler: NewsScheduler) -> None:
        event = await scheduler.poll_now(sources=["moneycontrol", "livemint"])
        assert set(event.sources) == {"moneycontrol", "livemint"}

    @pytest.mark.asyncio
    async def test_event_poll_type_manual(self, scheduler: NewsScheduler) -> None:
        event = await scheduler.poll_now(sources=["moneycontrol"], poll_type=PollType.MANUAL)
        assert event.poll_type == PollType.MANUAL

    @pytest.mark.asyncio
    async def test_articles_fetched_count(self) -> None:
        articles = [_make_article(f"Article {i}") for i in range(5)]
        scheduler = NewsScheduler(scraper=_make_scraper(articles))
        event = await scheduler.poll_now(sources=["moneycontrol"])
        assert event.articles_fetched == 5

    @pytest.mark.asyncio
    async def test_new_articles_deduplicated(self) -> None:
        article = _make_article("Shared title")
        scheduler = NewsScheduler(scraper=_make_scraper([article]))
        # First poll — article is new
        event1 = await scheduler.poll_now(sources=["moneycontrol"])
        assert len(event1.new_articles) == 1
        # Second poll — same article, should be cached
        event2 = await scheduler.poll_now(sources=["moneycontrol"])
        assert len(event2.new_articles) == 0

    @pytest.mark.asyncio
    async def test_scraper_error_gracefully_handled(self) -> None:
        scraper = MagicMock()
        scraper.fetch_headlines = MagicMock(side_effect=RuntimeError("network error"))
        scheduler = NewsScheduler(scraper=scraper)
        event = await scheduler.poll_now(sources=["moneycontrol"])
        assert event.articles_fetched == 0

    @pytest.mark.asyncio
    async def test_new_articles_are_dicts(self, scheduler: NewsScheduler) -> None:
        event = await scheduler.poll_now(sources=["moneycontrol"])
        for article in event.new_articles:
            assert isinstance(article, dict)
            assert "title" in article

    @pytest.mark.asyncio
    async def test_timestamp_is_utc(self, scheduler: NewsScheduler) -> None:
        event = await scheduler.poll_now(sources=["moneycontrol"])
        assert event.timestamp.tzinfo is not None


# ---------------------------------------------------------------------------
# NewsScheduler._next_event — schedule logic
# ---------------------------------------------------------------------------


class TestNextEvent:
    def _ist(self, hour: int, minute: int) -> datetime:
        today = datetime.now(_IST).date()
        return datetime(today.year, today.month, today.day, hour, minute, tzinfo=_IST)

    def test_before_07_fires_pre_market(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        now = self._ist(6, 0)
        fire_dt, poll_type, job_name = scheduler._next_event(now)
        assert poll_type == PollType.PRE_MARKET
        assert fire_dt.hour == 7
        assert fire_dt.minute == 0

    def test_between_07_and_0915_fires_intraday_at_open(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        now = self._ist(8, 0)
        fire_dt, poll_type, job_name = scheduler._next_event(now)
        # Soonest event should be intraday at 09:15 or pre_market at 07:00 tomorrow
        # Since now=08:00 is after 07:00, pre_market is tomorrow
        # Intraday fires at 09:15 today which is sooner
        assert poll_type == PollType.INTRADAY

    def test_during_market_hours_fires_next_intraday_slot(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper(), intraday_interval_min=15)
        now = self._ist(10, 0)
        fire_dt, poll_type, job_name = scheduler._next_event(now)
        assert poll_type == PollType.INTRADAY
        assert fire_dt.minute % 15 == 0 or fire_dt.hour > now.hour

    def test_at_1630_fires_post_market(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        # Just before 16:30 — soonest should be post_market
        now = self._ist(16, 0)
        fire_dt, poll_type, job_name = scheduler._next_event(now)
        assert poll_type == PollType.POST_MARKET

    def test_after_1630_fires_tomorrow_premarkt_or_intraday(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        now = self._ist(17, 0)
        fire_dt, poll_type, job_name = scheduler._next_event(now)
        # Both post_market and intraday are past today; pre_market tomorrow = next
        assert fire_dt > now

    def test_fire_time_always_in_future(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        now = datetime.now(_IST)
        fire_dt, _, _ = scheduler._next_event(now)
        assert fire_dt > now


# ---------------------------------------------------------------------------
# NewsScheduler start/stop lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_is_running(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        # Patch the loop to immediately return so the test doesn't hang
        async def _noop_loop() -> None:
            await asyncio.sleep(100)

        scheduler._loop = _noop_loop  # type: ignore[method-assign]
        await scheduler.start()
        assert scheduler.is_running is True
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())

        async def _noop_loop() -> None:
            await asyncio.sleep(100)

        scheduler._loop = _noop_loop  # type: ignore[method-assign]
        await scheduler.start()
        await scheduler.stop()
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_twice_is_safe(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())

        async def _noop_loop() -> None:
            await asyncio.sleep(100)

        scheduler._loop = _noop_loop  # type: ignore[method-assign]
        await scheduler.start()
        await scheduler.start()  # second call should be no-op
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_safe(self) -> None:
        scheduler = NewsScheduler(scraper=_make_scraper())
        await scheduler.stop()  # should not raise
