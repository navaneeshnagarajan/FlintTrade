"""The required Python summary fails unless every named sibling job succeeded."""

from __future__ import annotations

import pytest

from scripts.ci_require_jobs import evaluate, wait_for

pytestmark = pytest.mark.unit

REQUIRED = ["python-invariants", "python-shards (1)", "python-shards (2)"]


def _job(name: str, status: str = "completed", conclusion: str | None = "success") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def test_all_successful_jobs_pass():
    assert evaluate([_job(name) for name in REQUIRED], REQUIRED) == (True, [], [])


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", "timed_out", "neutral", None])
def test_any_other_conclusion_fails(conclusion):
    jobs = [_job(name) for name in REQUIRED[:-1]] + [_job(REQUIRED[-1], conclusion=conclusion)]
    done, failures, _ = evaluate(jobs, REQUIRED)
    assert done and failures == [f"{REQUIRED[-1]}: {conclusion}"]


def test_missing_and_running_jobs_are_pending():
    jobs = [_job(REQUIRED[0]), _job(REQUIRED[1], status="in_progress", conclusion=None)]
    assert evaluate(jobs, REQUIRED) == (False, [], REQUIRED[1:])


def test_a_failure_ends_the_wait_before_other_jobs_finish():
    jobs = [_job(REQUIRED[0], conclusion="failure")]
    done, failures, pending = evaluate(jobs, REQUIRED)
    assert done and failures and pending == REQUIRED[1:]


def test_unrelated_jobs_are_ignored():
    jobs = [_job(name) for name in REQUIRED] + [_job("node-core-tests", conclusion="failure")]
    assert evaluate(jobs, REQUIRED) == (True, [], [])


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_wait_returns_success_once_every_job_finishes(capsys):
    clock = _Clock()
    snapshots = iter([
        [_job(REQUIRED[0])],
        [_job(name) for name in REQUIRED[:2]] + [_job(REQUIRED[2], status="queued", conclusion=None)],
        [_job(name) for name in REQUIRED],
    ])
    assert wait_for(REQUIRED, lambda: next(snapshots), 600, 10, clock, clock.sleep) == 0
    assert clock.now == 20
    assert "All required Python checks passed" in capsys.readouterr().out


def test_wait_fails_on_a_failed_sibling(capsys):
    clock = _Clock()
    result = wait_for(REQUIRED, lambda: [_job(REQUIRED[1], conclusion="cancelled")], 600, 10, clock, clock.sleep)
    assert result == 1
    assert "python-shards (1): cancelled" in capsys.readouterr().out


def test_wait_fails_when_a_sibling_never_finishes(capsys):
    clock = _Clock()
    result = wait_for(REQUIRED, lambda: [_job(REQUIRED[0])], 60, 15, clock, clock.sleep)
    assert result == 1
    assert "Timed out waiting for: python-shards (1), python-shards (2)" in capsys.readouterr().out


def test_wait_retries_after_a_network_error():
    clock = _Clock()
    calls = iter([OSError("reset"), [_job(name) for name in REQUIRED]])

    def load():
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    assert wait_for(REQUIRED, load, 600, 10, clock, clock.sleep) == 0
