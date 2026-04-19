"""Historify bulk OHLCV downloader with resume support and delta sync.

Downloads OHLCV data for a list of (symbol, exchange) pairs across multiple
intervals, persists to DuckDB via the existing DataPipeline, and supports:

- Resuming an interrupted job (pending queue persisted in SQLite)
- Delta sync — only fetches bars after the last stored timestamp per symbol
- Progress callbacks for UI / progress-bar integration
- Concurrency cap via asyncio.Semaphore

Example::

    import asyncio
    from datetime import date
    from packages.core.src.openalgo_client import OpenAlgoClient
    from packages.historical.src.historify import HistorifyDownloader
    from packages.historical.src.pipeline import DataPipeline

    async def main():
        async with OpenAlgoClient() as client:
            pipeline = DataPipeline()
            pipeline.initialise()
            dl = HistorifyDownloader(client, pipeline)
            result = await dl.download_symbols(
                symbols=[("RELIANCE", "NSE"), ("NIFTY", "NSE_INDEX")],
                intervals=["1d", "1h"],
                from_date=date(2025, 1, 1),
                to_date=date(2025, 12, 31),
            )
            print(result)

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from packages.core.src.openalgo_client import OpenAlgoClient
from .downloader import DownloadResult, HistoricalDownloader
from .pipeline import DataPipeline, INTERVAL_TABLES

logger = logging.getLogger("flinttrade.historical.historify")

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class HistorifyResult:
    """Aggregated result from a bulk download run.

    Attributes:
        total: Total symbol×interval combinations attempted.
        succeeded: Combinations that produced at least one bar.
        failed: Combinations that returned zero bars or raised an error.
        skipped: Combinations skipped because they were already up-to-date.
        errors: List of error strings from failed combinations.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"HistorifyResult(total={self.total}, succeeded={self.succeeded}, "
            f"failed={self.failed}, skipped={self.skipped})"
        )


# ---------------------------------------------------------------------------
# Job queue (SQLite for durability across restarts)
# ---------------------------------------------------------------------------

_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS historify_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    interval    TEXT NOT NULL,
    from_date   TEXT NOT NULL,
    to_date     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (symbol, exchange, interval, from_date, to_date)
);
"""

_STATUS_PENDING = "pending"
_STATUS_DONE = "done"
_STATUS_ERROR = "error"


def _queue_db_path() -> Path:
    """Resolve queue SQLite path from env or workspace."""
    env = __import__("os").getenv("HISTORIFY_QUEUE_DB")
    if env:
        return Path(env)
    try:
        from packages.core.src.workspace import Workspace  # noqa: PLC0415
        return Workspace().fast_data_dir / "historify_queue.db"
    except Exception:
        return Path.home() / ".flinttrade" / "data" / "historify_queue.db"


class _JobQueue:
    """Durable job queue backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_QUEUE_DDL)
        self._conn.commit()

    def enqueue(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> None:
        """Insert a job, ignoring duplicates."""
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO historify_queue
                (symbol, exchange, interval, from_date, to_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [symbol, exchange, interval, from_date, to_date, _STATUS_PENDING, now, now],
        )
        self._conn.commit()

    def pending_jobs(self) -> list[dict[str, Any]]:
        """Return all pending (unfinished) jobs."""
        rows = self._conn.execute(
            "SELECT id, symbol, exchange, interval, from_date, to_date, error"
            " FROM historify_queue WHERE status = ? ORDER BY id",
            [_STATUS_PENDING],
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_done(self, job_id: int) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE historify_queue SET status = ?, updated_at = ? WHERE id = ?",
            [_STATUS_DONE, now, job_id],
        )
        self._conn.commit()

    def mark_error(self, job_id: int, error: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE historify_queue SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            [_STATUS_ERROR, error, now, job_id],
        )
        self._conn.commit()

    def clear_done(self) -> None:
        """Remove completed jobs to keep the queue tidy."""
        self._conn.execute("DELETE FROM historify_queue WHERE status = ?", [_STATUS_DONE])
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HistorifyDownloader
# ---------------------------------------------------------------------------


class HistorifyDownloader:
    """Bulk historical data downloader with resume support.

    Downloads OHLCV for a list of symbols across multiple intervals,
    persists to DuckDB, supports resume after interruption, and
    computes daily delta syncs.

    Args:
        client: Async :class:`~packages.core.src.openalgo_client.OpenAlgoClient`.
        storage: :class:`~packages.historical.src.pipeline.DataPipeline` instance.
        max_concurrent: Maximum concurrent symbol downloads (default 5).
        queue_db_path: Override path for the SQLite job queue.

    Example::

        dl = HistorifyDownloader(client, pipeline, max_concurrent=3)
        result = await dl.download_symbols(
            symbols=[("NIFTY", "NSE_INDEX"), ("RELIANCE", "NSE")],
            intervals=["1d"],
            from_date=date(2025, 1, 1),
            to_date=date(2025, 12, 31),
            progress_callback=lambda done, total: print(f"{done}/{total}"),
        )
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        storage: DataPipeline,
        max_concurrent: int = 5,
        queue_db_path: Path | None = None,
    ) -> None:
        self._client = client
        self._storage = storage
        self._max_concurrent = max_concurrent
        # Sync downloader for the underlying chunked fetch
        self._downloader = _AsyncDownloader(client)
        self._queue = _JobQueue(queue_db_path or _queue_db_path())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download_symbols(
        self,
        symbols: list[tuple[str, str]],
        intervals: list[str],
        from_date: date,
        to_date: date,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> HistorifyResult:
        """Download all symbol×interval combinations.

        Enqueues every combination to the durable job queue before starting
        so that :meth:`resume_queue` can pick up after an interruption.

        Args:
            symbols: List of ``(symbol, exchange)`` tuples.
            intervals: OHLCV intervals, e.g. ``["1d", "1h", "5m"]``.
            from_date: Inclusive start date.
            to_date: Inclusive end date.
            progress_callback: Called with ``(completed, total)`` after each job.

        Returns:
            :class:`HistorifyResult` with aggregate counts.
        """
        from_str = from_date.isoformat()
        to_str = to_date.isoformat()

        # Enqueue all combinations for durability
        for symbol, exchange in symbols:
            for interval in intervals:
                self._queue.enqueue(symbol, exchange, interval, from_str, to_str)

        jobs = self._queue.pending_jobs()
        result = HistorifyResult(total=len(jobs))
        completed = 0

        semaphore = asyncio.Semaphore(self._max_concurrent)

        async def _process(job: dict[str, Any]) -> None:
            nonlocal completed
            async with semaphore:
                await self._run_job(job, result)
            completed += 1
            if progress_callback:
                try:
                    progress_callback(completed, result.total)
                except Exception:
                    pass

        await asyncio.gather(*[_process(j) for j in jobs])
        self._queue.clear_done()

        logger.info("Bulk download complete: %s", result)
        return result

    async def delta_sync(
        self,
        symbols: list[tuple[str, str]],
        interval: str = "1d",
    ) -> int:
        """Sync only new bars since the last stored bar per symbol.

        For each (symbol, exchange), queries the latest stored timestamp from
        DuckDB, then downloads from the next day to today.

        Args:
            symbols: List of ``(symbol, exchange)`` tuples.
            interval: OHLCV interval (default ``"1d"``).

        Returns:
            Total number of new bars inserted across all symbols.
        """
        table = INTERVAL_TABLES.get(interval) or INTERVAL_TABLES.get("1d")
        if table is None:
            raise ValueError(f"Unknown interval for delta sync: {interval!r}")

        today = date.today()
        total_inserted = 0

        for symbol, exchange in symbols:
            last_ts = self._last_stored_date(table, symbol, exchange)
            if last_ts is None:
                # No prior data — full download for last 365 days
                start = today - timedelta(days=365)
                logger.info(
                    "delta_sync(%s/%s, %s): no prior data, fetching from %s",
                    symbol, exchange, interval, start,
                )
            else:
                start = last_ts + timedelta(days=1)
                if start > today:
                    logger.debug(
                        "delta_sync(%s/%s, %s): already up-to-date", symbol, exchange, interval
                    )
                    continue

            dl_result = await self._downloader.download(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start.isoformat(),
                end_date=today.isoformat(),
            )
            if dl_result.bars:
                inserted = self._storage.store_download(dl_result, interval)
                total_inserted += inserted
                logger.info(
                    "delta_sync(%s/%s, %s): +%d bars", symbol, exchange, interval, inserted
                )
            else:
                logger.debug(
                    "delta_sync(%s/%s, %s): no new bars", symbol, exchange, interval
                )

        return total_inserted

    def resume_queue(self) -> list[dict[str, Any]]:
        """Return pending downloads from an interrupted job.

        Returns:
            List of pending job dicts with keys ``symbol``, ``exchange``,
            ``interval``, ``from_date``, ``to_date``, ``error``.
        """
        return self._queue.pending_jobs()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_job(self, job: dict[str, Any], result: HistorifyResult) -> None:
        """Execute a single queued job and update result counters."""
        job_id: int = job["id"]
        symbol: str = job["symbol"]
        exchange: str = job["exchange"]
        interval: str = job["interval"]
        from_date: str = job["from_date"]
        to_date: str = job["to_date"]

        try:
            dl_result = await self._downloader.download(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=from_date,
                end_date=to_date,
            )
            if dl_result.bars:
                self._storage.store_download(dl_result, interval)
                result.succeeded += 1
                self._queue.mark_done(job_id)
                logger.info(
                    "Historify: %s/%s %s — %d bars", symbol, exchange, interval, dl_result.total_bars
                )
            else:
                errors = "; ".join(dl_result.errors) if dl_result.errors else "no bars returned"
                result.failed += 1
                result.errors.append(f"{symbol}/{exchange}@{interval}: {errors}")
                self._queue.mark_error(job_id, errors)
                logger.warning(
                    "Historify: %s/%s %s — no bars (errors: %s)",
                    symbol, exchange, interval, errors,
                )
        except Exception as exc:
            msg = str(exc)
            result.failed += 1
            result.errors.append(f"{symbol}/{exchange}@{interval}: {msg}")
            self._queue.mark_error(job_id, msg)
            logger.exception(
                "Historify: exception for %s/%s %s: %s", symbol, exchange, interval, msg
            )

    def _last_stored_date(
        self,
        table: str,
        symbol: str,
        exchange: str,
    ) -> date | None:
        """Return the date of the most recent stored bar, or None."""
        try:
            bars = self._storage.get_bars(table, symbol, exchange)
            if not bars:
                return None
            latest = bars[-1]["timestamp"]
            if isinstance(latest, datetime):
                return latest.date()
            if isinstance(latest, date):
                return latest
            return date.fromisoformat(str(latest)[:10])
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Thin async wrapper around the sync HistoricalDownloader
# ---------------------------------------------------------------------------


class _AsyncDownloader:
    """Runs the synchronous HistoricalDownloader in a thread-pool executor."""

    def __init__(self, client: OpenAlgoClient) -> None:
        self._client = client

    async def download(
        self,
        symbol: str,
        exchange: str,
        interval: str,
        start_date: str,
        end_date: str,
    ) -> DownloadResult:
        """Async shim — delegates chunked download to async OpenAlgoClient."""
        from .downloader import (  # noqa: PLC0415
            _INTERVAL_MAP,
            _INTRADAY_INTERVALS,
            _DEFAULT_CHUNK_DAYS_INTRADAY,
            _DEFAULT_CHUNK_DAYS_DAILY,
            compute_date_chunks,
            DownloadResult,
        )
        from packages.core.src.models import OHLCV  # noqa: PLC0415
        from datetime import date as _date  # noqa: PLC0415

        canonical = _INTERVAL_MAP.get(interval, interval)
        result = DownloadResult(
            symbol=symbol,
            exchange=exchange,
            interval=canonical,
            start_date=start_date,
            end_date=end_date,
        )

        start = _date.fromisoformat(start_date)
        end = _date.fromisoformat(end_date)
        if start > end:
            result.errors.append(f"start_date {start_date} is after end_date {end_date}")
            return result

        is_intraday = canonical in _INTRADAY_INTERVALS
        chunk_days = _DEFAULT_CHUNK_DAYS_INTRADAY if is_intraday else _DEFAULT_CHUNK_DAYS_DAILY
        chunks = compute_date_chunks(start, end, chunk_days)

        all_bars: list[OHLCV] = []
        for i, (c_start, c_end) in enumerate(chunks, 1):
            c_start_str = c_start.isoformat()
            c_end_str = c_end.isoformat()
            try:
                bars = await self._client.history(
                    symbol=symbol,
                    exchange=exchange,
                    interval=canonical,
                    start_date=c_start_str,
                    end_date=c_end_str,
                )
                all_bars.extend(bars)
                result.chunks_fetched += 1
            except Exception as exc:
                msg = f"Chunk {i} ({c_start_str} to {c_end_str}) failed: {exc}"
                result.errors.append(msg)
                logger.warning("_AsyncDownloader: %s", msg)

        # Deduplicate and sort
        seen: set[str] = set()
        unique: list[OHLCV] = []
        for bar in all_bars:
            if bar.timestamp not in seen:
                seen.add(bar.timestamp)
                unique.append(bar)
        unique.sort(key=lambda b: b.timestamp)
        result.bars = unique
        return result
