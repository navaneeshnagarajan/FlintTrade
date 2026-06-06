"""Background download-job manager for historical OHLCV downloads.

The terminal needs a non-blocking "download everything" experience with a live
progress bar, a time-remaining (ETA) estimate, and a safety monitor that refuses
to start when the disk is nearly full. The underlying
:class:`~flinttrade_historical.historify.HistorifyDownloader` already persists
bars and reports ``(completed, total)`` progress — this manager runs it on a
background thread, tracks progress/ETA, and exposes pollable job status so a
Flask route can start a job and return immediately.

The manager is deliberately decoupled from the downloader: ``start()`` takes a
``runner`` coroutine factory, so it can be unit-tested with a fake runner and
re-used for any progress-reporting async download.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger("flinttrade.historical.historify_jobs")

# Progress callback: called with (completed, total).
ProgressCallback = Callable[[int, int], None]
# Runner factory: given a progress callback, returns the awaitable that performs
# the download and reports progress through it.
RunnerFactory = Callable[[ProgressCallback], Awaitable[Any]]

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_REFUSED = "refused"
STATUS_ABORTED = "aborted"  # disk filled mid-run; stopped to protect the disk


class _DiskAbort(Exception):
    """Raised from the progress callback to stop a run when the disk fills."""


@dataclass
class DownloadJob:
    """Snapshot of a single download job's state."""

    job_id: str
    status: str
    total: int
    completed: int = 0
    started_at: float | None = None
    updated_at: float | None = None
    eta_seconds: float | None = None
    free_disk_mb: float | None = None
    error: str | None = None
    message: str = ""
    # Filesystem path being written to — kept so the disk-safety check can be
    # re-run mid-flight (not only at start).
    storage_path: str | None = None

    @property
    def progress_pct(self) -> float:
        if self.total <= 0:
            return 0.0
        return round(min(100.0, (self.completed / self.total) * 100.0), 1)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["progress_pct"] = self.progress_pct
        return d


class HistorifyJobManager:
    """Runs progress-reporting async downloads as background jobs.

    Args:
        min_free_disk_mb: Refuse to start a job when free disk is below this.
        clock: Monotonic clock (injectable for tests).
        recheck_every: Re-run the disk-safety check every N completed items
            during the run (0 disables mid-run re-checks). ``shutil.disk_usage``
            is one cheap syscall, so this keeps latency tight.
    """

    def __init__(
        self,
        min_free_disk_mb: float = 500.0,
        clock: Callable[[], float] = time.monotonic,
        recheck_every: int = 200,
    ) -> None:
        self._jobs: dict[str, DownloadJob] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._min_free_disk_mb = min_free_disk_mb
        self._clock = clock
        self._recheck_every = recheck_every

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def check_disk_safety(self, path: str) -> tuple[bool, float]:
        """Return ``(ok, free_mb)`` for the filesystem holding ``path``."""
        try:
            usage = shutil.disk_usage(path)
            free_mb = usage.free / (1024 * 1024)
        except OSError as exc:  # pragma: no cover - defensive
            logger.warning("Disk safety check failed for %s: %s", path, exc)
            return True, -1.0  # do not block on an unreadable path
        return free_mb >= self._min_free_disk_mb, free_mb

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._counter += 1
        return f"job-{self._counter}"

    def start(
        self,
        *,
        total: int,
        runner: RunnerFactory,
        storage_path: str,
    ) -> DownloadJob:
        """Start a background download job and return its initial snapshot.

        Refuses (status ``refused``) when the disk safety check fails, so the
        caller can surface a clear message instead of filling the disk.
        """
        with self._lock:
            job_id = self._next_id()
            ok, free_mb = self.check_disk_safety(storage_path)
            if not ok:
                job = DownloadJob(
                    job_id=job_id,
                    status=STATUS_REFUSED,
                    total=total,
                    free_disk_mb=round(free_mb, 1),
                    message=(
                        f"Refused: only {free_mb:.0f} MB free (need "
                        f"{self._min_free_disk_mb:.0f} MB). Free up disk and retry."
                    ),
                )
                self._jobs[job_id] = job
                return job

            job = DownloadJob(
                job_id=job_id,
                status=STATUS_QUEUED,
                total=total,
                started_at=self._clock(),
                updated_at=self._clock(),
                free_disk_mb=round(free_mb, 1),
                message="Queued",
                storage_path=storage_path,
            )
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run,
            args=(job_id, runner),
            name=f"historify-{job_id}",
            daemon=True,
        )
        thread.start()
        return self.get(job_id) or job

    def _run(self, job_id: str, runner: RunnerFactory) -> None:
        self._update(job_id, status=STATUS_RUNNING, message="Downloading…")

        def on_progress(completed: int, total: int) -> None:
            self._record_progress(job_id, completed, total)

        try:
            asyncio.run(runner(on_progress))
            self._update(job_id, status=STATUS_DONE, message="Complete")
        except _DiskAbort:
            # Status was already set to ABORTED in the progress callback; the
            # runner stopped because the disk filled mid-run. Not an error.
            logger.warning("Download job %s aborted: disk safety breached mid-run", job_id)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the job
            logger.exception("Download job %s failed", job_id)
            self._update(job_id, status=STATUS_ERROR, error=str(exc), message="Failed")

    # ------------------------------------------------------------------
    # State updates / reads
    # ------------------------------------------------------------------

    def _record_progress(self, job_id: str, completed: int, total: int) -> None:
        now = self._clock()
        recheck_path: str | None = None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.completed = completed
            if total > 0:
                job.total = total
            job.updated_at = now
            # ETA from the average rate since start.
            elapsed = now - (job.started_at or now)
            if completed > 0 and elapsed > 0 and total > completed:
                rate = completed / elapsed  # items per second
                job.eta_seconds = round((total - completed) / rate, 1)
            elif total > 0 and completed >= total:
                job.eta_seconds = 0.0
            # Decide (under the lock) whether this tick re-checks the disk.
            if (
                self._recheck_every > 0
                and completed > 0
                and completed % self._recheck_every == 0
            ):
                recheck_path = job.storage_path

        # The disk check (a syscall) runs OUTSIDE the lock. A long backfill that
        # passed the start-time threshold can still fill the disk; abort the run
        # rather than exhaust it.
        if recheck_path is not None:
            ok, free_mb = self.check_disk_safety(recheck_path)
            if not ok:
                self._update(
                    job_id,
                    status=STATUS_ABORTED,
                    free_disk_mb=round(free_mb, 1),
                    message=(
                        f"Aborted mid-run: only {free_mb:.0f} MB free "
                        f"(need {self._min_free_disk_mb:.0f} MB). Free up disk and retry."
                    ),
                )
                raise _DiskAbort(job_id)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = self._clock()

    def get(self, job_id: str) -> DownloadJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else DownloadJob(**asdict(job))

    def list_jobs(self) -> list[DownloadJob]:
        with self._lock:
            return [DownloadJob(**asdict(j)) for j in self._jobs.values()]
