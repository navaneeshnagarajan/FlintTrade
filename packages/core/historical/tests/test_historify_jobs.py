"""Unit tests for the historical download job manager."""

from __future__ import annotations

import time

import pytest

from flinttrade_historical.historify_jobs import (
    STATUS_ABORTED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_REFUSED,
    DownloadJob,
    HistorifyJobManager,
)

pytestmark = pytest.mark.unit


def _wait_terminal(mgr: HistorifyJobManager, job_id: str, timeout: float = 5.0) -> DownloadJob:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = mgr.get(job_id)
        if snap and snap.status in (STATUS_DONE, STATUS_ERROR, STATUS_REFUSED):
            return snap
        time.sleep(0.02)
    snap = mgr.get(job_id)
    assert snap is not None
    return snap


def test_refuses_when_disk_below_threshold() -> None:
    # An impossibly high threshold forces the safety check to fail.
    mgr = HistorifyJobManager(min_free_disk_mb=10**15)

    async def runner(_progress):  # pragma: no cover - must not run
        raise AssertionError("runner should not start when refused")

    job = mgr.start(total=5, runner=runner, storage_path=".")
    assert job.status == STATUS_REFUSED
    assert "Refused" in job.message
    assert job.free_disk_mb is not None


def test_completes_and_reports_progress() -> None:
    mgr = HistorifyJobManager(min_free_disk_mb=0)

    async def runner(progress):
        for i in range(1, 4):
            progress(i, 3)
        return None

    job = mgr.start(total=3, runner=runner, storage_path=".")
    final = _wait_terminal(mgr, job.job_id)
    assert final.status == STATUS_DONE
    assert final.completed == 3
    assert final.progress_pct == 100.0


def test_error_status_on_runner_failure() -> None:
    mgr = HistorifyJobManager(min_free_disk_mb=0)

    async def runner(_progress):
        raise RuntimeError("boom")

    job = mgr.start(total=2, runner=runner, storage_path=".")
    final = _wait_terminal(mgr, job.job_id)
    assert final.status == STATUS_ERROR
    assert final.error == "boom"


def test_aborts_mid_run_when_disk_fills() -> None:
    # The start-time check passes, but a mid-run re-check fails — a long backfill
    # must abort rather than exhaust the disk.
    mgr = HistorifyJobManager(min_free_disk_mb=500.0, recheck_every=2)
    calls = {"n": 0}

    def fake_check(_path: str) -> tuple[bool, float]:
        calls["n"] += 1
        # 1st call = start() → pass; subsequent (mid-run) → fail.
        return (calls["n"] == 1, 5000.0 if calls["n"] == 1 else 50.0)

    mgr.check_disk_safety = fake_check  # type: ignore[method-assign]

    progressed: list[int] = []

    async def runner(progress):
        for i in range(1, 11):
            progress(i, 10)  # raises the disk-abort at i=2 (recheck_every=2)
            progressed.append(i)

    job = mgr.start(total=10, runner=runner, storage_path="/data")

    deadline = time.time() + 5.0
    while time.time() < deadline:
        snap = mgr.get(job.job_id)
        if snap and snap.status == STATUS_ABORTED:
            break
        time.sleep(0.02)

    final = mgr.get(job.job_id)
    assert final.status == STATUS_ABORTED
    assert "Aborted mid-run" in final.message
    assert progressed == [1]  # stopped: i=2 raised before its append


def test_eta_estimated_from_rate() -> None:
    # Fixed clock at 110; the seeded job started at 100 → 10s elapsed.
    mgr = HistorifyJobManager(min_free_disk_mb=0, clock=lambda: 110.0)
    seeded = DownloadJob(job_id="job-x", status="running", total=10, started_at=100.0)
    mgr._jobs["job-x"] = seeded  # noqa: SLF001 - white-box test of ETA maths

    mgr._record_progress("job-x", 2, 10)  # noqa: SLF001
    snap = mgr.get("job-x")
    assert snap is not None
    # rate = 2/10 = 0.2 items/s; remaining = 8 → eta = 40s
    assert snap.eta_seconds == 40.0
    assert snap.progress_pct == 20.0


def test_disk_safety_returns_free_space() -> None:
    mgr = HistorifyJobManager(min_free_disk_mb=0)
    ok, free_mb = mgr.check_disk_safety(".")
    assert ok is True
    assert free_mb > 0


def test_job_ids_are_unique_and_listed() -> None:
    mgr = HistorifyJobManager(min_free_disk_mb=0)

    async def runner(progress):
        progress(1, 1)

    a = mgr.start(total=1, runner=runner, storage_path=".")
    b = mgr.start(total=1, runner=runner, storage_path=".")
    assert a.job_id != b.job_id
    _wait_terminal(mgr, a.job_id)
    _wait_terminal(mgr, b.job_id)
    assert {j.job_id for j in mgr.list_jobs()} == {a.job_id, b.job_id}
