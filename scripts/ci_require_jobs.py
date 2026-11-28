"""Wait for sibling jobs in the current workflow run and require them to pass.

The required ``python-tests`` check runs one Python shard itself and then uses
this script to confirm that the root invariants and every other shard in the
same run succeeded. Doing the summary inside a job that already holds a runner
avoids a separate summary job that would queue for a fresh runner after the
shards finish.

Usage::

    python scripts/ci_require_jobs.py --job python-invariants \\
        --job "python-shards (1)" --job "python-shards (2)"

It reads ``GITHUB_TOKEN``, ``GITHUB_REPOSITORY`` and ``GITHUB_RUN_ID`` from the
environment, polls the run's latest job attempts, and exits non-zero when any
named job ends in anything other than success, or when a job never appears or
never finishes before the deadline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from collections.abc import Callable, Iterable

PASSING = "success"


def evaluate(jobs: Iterable[dict], required: list[str]) -> tuple[bool, list[str], list[str]]:
    """Return ``(done, failures, pending)`` for the required job names.

    ``jobs`` are GitHub job objects (``name``, ``status``, ``conclusion``).
    A required job that is absent or not yet completed is pending. A completed
    job with any conclusion other than success is a failure, including
    skipped, cancelled, neutral and timed out.
    """
    latest: dict[str, dict] = {}
    for job in jobs:
        name = job.get("name")
        if isinstance(name, str):
            latest[name] = job
    failures: list[str] = []
    pending: list[str] = []
    for name in required:
        job = latest.get(name)
        if job is None or job.get("status") != "completed":
            pending.append(name)
        elif job.get("conclusion") != PASSING:
            failures.append(f"{name}: {job.get('conclusion')}")
    done = bool(failures) or not pending
    return done, failures, pending


def fetch_jobs(repo: str, run_id: str, token: str) -> list[dict]:
    jobs: list[dict] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}"
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(request, timeout=30) as response:
            batch = json.load(response).get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


def wait_for(
    required: list[str],
    load: Callable[[], list[dict]],
    deadline_seconds: float,
    interval_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    end = clock() + deadline_seconds
    while True:
        try:
            done, failures, pending = evaluate(load(), required)
        except OSError as exc:
            print(f"Could not read job status yet ({exc}); retrying.")
            done, failures, pending = False, [], list(required)
        if done:
            if failures:
                print("A required Python check failed, was cancelled or did not run:")
                for line in failures:
                    print(f"  {line}")
                return 1
            print("All required Python checks passed: " + ", ".join(required))
            return 0
        if clock() >= end:
            print("Timed out waiting for: " + ", ".join(pending))
            return 1
        sleep(interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--job", action="append", required=True, dest="jobs")
    parser.add_argument("--deadline-minutes", type=float, default=30.0)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        run_id = os.environ["GITHUB_RUN_ID"]
        token = os.environ["GITHUB_TOKEN"]
    except KeyError as missing:
        print(f"Missing environment variable {missing}.", file=sys.stderr)
        return 1
    return wait_for(
        args.jobs,
        lambda: fetch_jobs(repo, run_id, token),
        args.deadline_minutes * 60,
        args.interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
