"""Tests for the overnight strategy-optimisation cron trigger."""

from __future__ import annotations

import pytest

from flinttrade_automation.cron_manager import CronManager

pytestmark = pytest.mark.unit


def test_registered_and_fires_when_optimiser_injected():
    cron = CronManager()
    fired: list[bool] = []
    cron.overnight_optimiser = lambda: fired.append(True)
    cron.register_builtin_jobs()
    assert "overnight_optimise_job" in cron._jobs  # noqa: SLF001
    cron.run_now("overnight_optimise_job")
    assert fired == [True]


def test_not_registered_without_an_optimiser():
    cron = CronManager()
    cron.register_builtin_jobs()
    assert "overnight_optimise_job" not in cron._jobs  # noqa: SLF001


def test_optimiser_failure_does_not_crash_the_scheduler():
    cron = CronManager()

    def boom() -> None:
        raise RuntimeError("optimisation blew up")

    cron.overnight_optimiser = boom
    cron.register_builtin_jobs()
    # Must not propagate — a failed overnight sweep can't take down cron.
    cron.run_now("overnight_optimise_job")


def test_scheduled_for_the_early_morning_on_weekdays():
    from flinttrade_automation.cron_manager import DEFAULT_JOBS

    args = DEFAULT_JOBS["overnight_optimise_job"]["trigger_args"]
    assert args["hour"] == 2
    assert args["day_of_week"] == "mon-fri"
