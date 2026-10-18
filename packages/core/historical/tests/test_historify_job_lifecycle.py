"""The real historical worker remains owned until its runner actually exits."""
from __future__ import annotations

import asyncio
import threading

import pytest

from flinttrade_historical.historify_jobs import HistorifyJobManager

pytestmark = pytest.mark.integration


def test_close_refuses_new_jobs_and_retains_a_running_worker_for_retry(tmp_path):
    manager = HistorifyJobManager(min_free_disk_mb=0)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    async def held(progress):
        entered.set()
        await asyncio.to_thread(release.wait)
        progress(1, 1)
        finished.set()

    job = manager.start(total=1, runner=held, storage_path=str(tmp_path))
    try:
        assert entered.wait(2)
        close = getattr(manager, "close", None)
        assert callable(close), "historical jobs have no close/drain owner"
        assert close(timeout=0.01) is False
        assert not finished.is_set()
        assert manager.get(job.job_id).status == "running"
        refused = manager.start(total=1, runner=held, storage_path=str(tmp_path))
        assert refused.status == "refused"
        assert refused.error == "historical_owner_retired"
        release.set()
        assert close(timeout=2) is True
        assert finished.is_set()
        assert manager.get(job.job_id).status == "done"
        assert close(timeout=0) is True
    finally:
        release.set()
        assert finished.wait(2)
        close = getattr(manager, "close", None)
        if callable(close):
            assert close(timeout=2)


def test_close_waits_for_worker_cleanup_after_runner_error(tmp_path):
    manager = HistorifyJobManager(min_free_disk_mb=0)
    entered, release = threading.Event(), threading.Event()

    async def fails(_progress):
        entered.set()
        await asyncio.to_thread(release.wait)
        raise RuntimeError("synthetic source refusal")

    job = manager.start(total=1, runner=fails, storage_path=str(tmp_path))
    try:
        assert entered.wait(2)
        close = getattr(manager, "close", None)
        assert callable(close), "historical jobs have no retained shutdown handle"
        assert close(timeout=0.01) is False
        release.set()
        assert close(timeout=2) is True
        assert manager.get(job.job_id).status == "error"
    finally:
        release.set()
        close = getattr(manager, "close", None)
        if callable(close):
            assert close(timeout=2)
