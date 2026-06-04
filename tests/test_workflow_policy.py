"""CI-policy guardrail: keep GitHub Actions usage inside best practice.

This test exists because of a concrete incident. A heavy, daily,
multi-platform CI footprint — macOS runners are billed at 10x the Linux
minute rate and Windows at 2x — on a young GitHub account tripped the
Actions abuse / over-usage auto-flagging, and Actions was disabled
account-wide. The remediation was to right-size CI to GitHub's published
best practices and to add this guardrail so that no future change (human
or agent) silently re-introduces the footprint that caused the flag.

The policy enforced here, asserted against every ``.github/workflows/*.yml``:

1. **No expensive runner on a cheap, frequent trigger.** A job that uses a
   ``macos-*`` or ``windows-*`` runner must not be reachable from a
   ``push`` / ``pull_request`` trigger or a daily-or-more-frequent
   ``schedule`` cron. macOS / Windows coverage is allowed only under a
   weekly-or-less-frequent ``schedule`` or a manual ``workflow_dispatch``
   (release-tag pushes are covered by the same rule — a tag push is still a
   push, so cross-platform jobs gate behind ``workflow_dispatch`` /
   schedule, never an unconditional push).
2. **Every job declares ``timeout-minutes``.** A missing timeout is the
   single clearest runaway signal an abuse heuristic watches for; a hung
   job otherwise burns minutes up to the six-hour default.
3. **Every workflow declares a top-level ``permissions`` block.** Pinning
   the token to least privilege (default ``contents: read``) is both a
   security control and a usage-hygiene signal.

The check is deliberately tolerant of the matrix and ``${{ }}`` expression
syntax that real workflows use: runner operating systems are matched by
substring against both the literal ``runs-on`` value and every value of any
``strategy.matrix`` list, so ``runs-on: ${{ matrix.os }}`` with
``matrix.os: [ubuntu-latest, macos-latest]`` is resolved correctly.

Stdlib + PyYAML only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

# Runner operating systems that cost more than the baseline Linux runner and
# therefore must never sit behind a cheap, frequent trigger.
_EXPENSIVE_OS_TOKENS = ("macos", "windows")

# Triggers that fire cheaply and frequently. A macOS / Windows job behind any
# of these is the footprint that tripped the abuse flag.
_FREQUENT_PUSH_TRIGGERS = ("push", "pull_request", "pull_request_target")

# Cron day-of-week / day-of-month tokens that still mean "every day", i.e. do
# not actually narrow the schedule below daily.
_EVERY_DAY_DOW = {"*", "*/1", "0-6", "0-7", "1-7", "sun-sat", "mon-sun"}
_EVERY_DAY_DOM = {"*", "*/1", "1-31"}


def _load_workflows() -> list[tuple[str, dict[str, Any]]]:
    """Parse every workflow YAML; return ``(relative_path, document)`` pairs."""
    workflows: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(_WORKFLOW_DIR.glob("*.yml")) + sorted(_WORKFLOW_DIR.glob("*.yaml")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(doc, dict), f"{rel}: workflow did not parse to a mapping"
        workflows.append((rel, doc))
    return workflows


# Collected once so every parametrised case shares the same parse.
_WORKFLOWS = _load_workflows()
_WORKFLOW_IDS = [rel for rel, _ in _WORKFLOWS]


def _on_block(doc: dict[str, Any]) -> dict[str, Any]:
    """Return the workflow ``on:`` mapping.

    PyYAML parses the bare key ``on`` as the boolean ``True`` (YAML 1.1
    treats ``on``/``off``/``yes``/``no`` as booleans), so accept both keys.
    Normalise list / string trigger forms (``on: [push, pull_request]`` or
    ``on: push``) into a mapping with empty bodies.
    """
    raw = doc.get("on", doc.get(True))
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return {str(key): None for key in raw}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    return {}


def _cron_is_daily_or_more_frequent(expr: str) -> bool:
    """True if a five-field cron expression can fire on every day.

    A cron is weekly-or-less-frequent (and so allowed for expensive runners)
    when it restricts the day-of-month or the day-of-week to something other
    than "every day". Anything that leaves both wide open fires at least
    daily. Robust to the common "every day" encodings rather than evaluating
    the full cron grammar.
    """
    fields = expr.split()
    if len(fields) != 5:
        # Non-standard expression — treat conservatively as frequent so it
        # cannot smuggle an expensive runner past the gate.
        return True
    dom = fields[2].strip().lower()
    dow = fields[4].strip().lower()
    dom_restricted = dom not in _EVERY_DAY_DOM
    dow_restricted = dow not in _EVERY_DAY_DOW
    return not (dom_restricted or dow_restricted)


def _schedule_crons(on_block: dict[str, Any]) -> list[str]:
    schedule = on_block.get("schedule")
    if not isinstance(schedule, list):
        return []
    crons: list[str] = []
    for entry in schedule:
        if isinstance(entry, dict) and "cron" in entry:
            crons.append(str(entry["cron"]))
    return crons


def _has_frequent_trigger(on_block: dict[str, Any]) -> tuple[bool, list[str]]:
    """Does this workflow fire on a cheap, frequent trigger?

    Returns ``(is_frequent, reasons)`` where ``reasons`` names each offending
    trigger so the assertion message can be specific.
    """
    reasons: list[str] = []
    for trigger in _FREQUENT_PUSH_TRIGGERS:
        if trigger in on_block:
            reasons.append(f"`{trigger}` trigger")
    for cron in _schedule_crons(on_block):
        if _cron_is_daily_or_more_frequent(cron):
            reasons.append(f"daily-or-more-frequent cron '{cron}'")
    return bool(reasons), reasons


# Match `github.event_name == 'schedule'` / `== "workflow_dispatch"` and the
# membership forms `contains(fromJSON('["schedule","workflow_dispatch"]'), ...)`.
_EVENT_NAME_EQ_RE = re.compile(r"github\.event_name\s*==\s*['\"]([a-z_]+)['\"]")


def _if_restricts_to_safe_events(if_expr: str | None) -> bool:
    """True if a job-level ``if:`` confines the job to safe events only.

    The safe events are ``schedule`` and ``workflow_dispatch``. We recognise
    the idiomatic guard ``if: github.event_name == 'schedule'`` (optionally
    OR-ed with ``workflow_dispatch``). Any reference to a frequent event name,
    or an ``if:`` we cannot prove is safe, returns False so the job is still
    judged against the workflow triggers — i.e. we fail closed.
    """
    if not if_expr:
        return False
    referenced = _EVENT_NAME_EQ_RE.findall(if_expr)
    if not referenced:
        return False
    safe = {"schedule", "workflow_dispatch"}
    return all(name in safe for name in referenced)


def _runner_os_strings(job: dict[str, Any]) -> list[str]:
    """Every operating-system string a job can run on.

    Combines the literal ``runs-on`` value with every value found in any
    ``strategy.matrix`` list, so a ``runs-on: ${{ matrix.os }}`` job is
    resolved through its ``matrix.os`` list. Returned lower-cased for
    substring matching against ``_EXPENSIVE_OS_TOKENS``.
    """
    found: list[str] = []

    runs_on = job.get("runs-on")
    if isinstance(runs_on, str):
        found.append(runs_on)
    elif isinstance(runs_on, list):
        found.extend(str(item) for item in runs_on)

    strategy = job.get("strategy")
    if isinstance(strategy, dict):
        matrix = strategy.get("matrix")
        if isinstance(matrix, dict):
            for value in matrix.values():
                if isinstance(value, list):
                    found.extend(str(item) for item in value)
                elif isinstance(value, str):
                    found.append(value)
            # matrix `include:` entries can introduce extra os values.
            include = matrix.get("include")
            if isinstance(include, list):
                for entry in include:
                    if isinstance(entry, dict):
                        for value in entry.values():
                            found.append(str(value))

    return [s.lower() for s in found]


def _expensive_os_in(os_strings: list[str]) -> list[str]:
    hits: list[str] = []
    for token in _EXPENSIVE_OS_TOKENS:
        for os_string in os_strings:
            if token in os_string:
                hits.append(os_string)
    # De-duplicate while preserving order.
    return list(dict.fromkeys(hits))


def _jobs(doc: dict[str, Any]) -> dict[str, Any]:
    jobs = doc.get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def test_workflows_exist_and_parse() -> None:
    """Sanity guard: the workflow directory is present and every file parses.

    Without this, an unparseable YAML or an empty directory would make the
    parametrised policy tests silently pass with nothing to check.
    """
    assert _WORKFLOW_DIR.is_dir(), f"missing workflow directory: {_WORKFLOW_DIR}"
    assert _WORKFLOWS, f"no workflow files found under {_WORKFLOW_DIR}"


@pytest.mark.parametrize(("rel", "doc"), _WORKFLOWS, ids=_WORKFLOW_IDS)
def test_workflow_declares_top_level_permissions(rel: str, doc: dict[str, Any]) -> None:
    """Policy 3: every workflow pins the token with a top-level permissions block."""
    permissions = doc.get("permissions")
    assert permissions is not None, (
        f"{rel}: workflow has no top-level `permissions:` block. "
        "Add a least-privilege block (default `permissions:\n  contents: read`) "
        "and widen only the specific scope a job needs."
    )


@pytest.mark.parametrize(("rel", "doc"), _WORKFLOWS, ids=_WORKFLOW_IDS)
def test_every_job_declares_timeout(rel: str, doc: dict[str, Any]) -> None:
    """Policy 2: every job sets timeout-minutes (the runaway-job guard)."""
    missing: list[str] = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        # Reusable-workflow calls (`uses:` at job level) cannot set
        # timeout-minutes; the timeout lives in the called workflow.
        if "uses" in job and "steps" not in job:
            continue
        if "timeout-minutes" not in job:
            missing.append(job_name)
    assert not missing, (
        f"{rel}: job(s) without `timeout-minutes`: {', '.join(missing)}. "
        "A missing timeout lets a hung job burn minutes up to the 6-hour "
        "default and is the clearest abuse signal. Add a sensible value "
        "(lint ~10, tests ~30, cross-platform ~45)."
    )


@pytest.mark.parametrize(("rel", "doc"), _WORKFLOWS, ids=_WORKFLOW_IDS)
def test_no_expensive_runner_on_frequent_trigger(rel: str, doc: dict[str, Any]) -> None:
    """Policy 1: macOS / Windows jobs never sit behind push / PR / daily cron.

    Expensive runners are allowed only under a weekly-or-less-frequent
    schedule or a manual ``workflow_dispatch``.
    """
    on_block = _on_block(doc)
    is_frequent, reasons = _has_frequent_trigger(on_block)
    if not is_frequent:
        # Workflow only fires on safe triggers (weekly schedule /
        # workflow_dispatch / comment events) — expensive runners are fine.
        return

    violations: list[str] = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        expensive = _expensive_os_in(_runner_os_strings(job))
        if not expensive:
            continue
        if _if_restricts_to_safe_events(job.get("if")):
            # The job's own `if:` confines it to schedule / workflow_dispatch,
            # so the frequent workflow trigger never reaches it.
            continue
        violations.append(
            f"job '{job_name}' runs on {expensive} but is reachable via "
            f"{', '.join(reasons)}"
        )

    assert not violations, (
        f"{rel}: expensive runner(s) on a cheap/frequent trigger:\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\nMove macOS / Windows coverage to a weekly-or-less `schedule` "
        "plus `workflow_dispatch` (see .github/workflows/nightly-cross-platform.yml), "
        "or gate the job with `if: github.event_name == 'schedule' || "
        "github.event_name == 'workflow_dispatch'`."
    )
