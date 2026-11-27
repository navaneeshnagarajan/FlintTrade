"""Focused policy test: required Test workflow reachability for branch protection.

The Test workflow (and its check contexts) must never be entirely suppressed
by a top-level `pull_request.paths-ignore` when targeting protected branches
main or dev. Such suppression would cause the PR to omit the required check
contexts, leaving the PR deadlocked / blocked from normal merge under branch
protection (it cannot merge through normal branch protection).

Filtering for expensive lanes stays inside the `changed-surfaces` job and
per-job `if:` conditions (already present). This test only guards the
trigger-level reachability.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "test.yml"


def _normalise_on(doc: dict) -> dict:
    """Normalise the ``on:`` block (handles YAML 1.1 ``on`` -> True)."""
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


def test_test_workflow_pull_request_trigger_has_no_paths_ignore():
    """Non-draft PRs to main/dev must always create the Test workflow run.

    Top-level paths-ignore under pull_request would cause the entire workflow
    (and therefore every job's check context) to be omitted for changes that
    only touch the ignored paths. This breaks branch-protection required checks.
    """
    doc = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), "test.yml must parse to a mapping"

    on_block = _normalise_on(doc)
    assert "pull_request" in on_block, "Test workflow must declare a pull_request trigger"

    pr_config = on_block["pull_request"]
    if pr_config is None:
        pr_config = {}

    assert isinstance(pr_config, dict), "pull_request config must be a mapping"

    # The critical invariant: no top-level path filter on the PR trigger.
    # Either `paths-ignore` or a positive `paths:` list would omit the whole
    # Test workflow (and therefore every required check context) for PRs
    # outside that filter. push may keep its own; job-level if: remains for cost.
    for forbidden in ("paths-ignore", "paths"):
        assert forbidden not in pr_config, (
            f"pull_request trigger must not contain {forbidden}; "
            "otherwise PRs outside that filter skip the whole Test workflow "
            "and omit the required check contexts on main/dev."
        )

    # Sanity: still targets the protected branches
    branches = pr_config.get("branches", [])
    if isinstance(branches, str):
        branches = [branches]
    # Set containment (both main AND dev required; mutation-sensitive)
    required = {"main", "dev"}
    assert required.issubset(set(branches)), (
        f"pull_request.branches must contain both main and dev as a set; "
        f"got {branches}"
    )


def test_protected_branch_pushes_do_not_bypass_the_exhaustive_gate():
    document = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    push = _normalise_on(document)["push"]
    assert {"main", "dev"} <= set(push["branches"])
    assert not {"paths", "paths-ignore"} & push.keys(), (
        "Protected-branch pushes must retain Site attribution and the full gate, including NOTICE/LICENSE changes"
    )


# Classifier behaviours are exercised against the shared implementation in
# test_check_changes.py; this file checks that the workflow uses that plan.

def _classify_script(job: dict) -> str:
    return next(step["run"] for step in job["steps"] if step.get("id") == "classify")


def test_classifier_outputs_reach_each_required_surface():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    classifier = jobs["changed-surfaces"]
    script = _classify_script(classifier)
    assert "scripts/check_changes.py" in script
    assert "--full --github-output" in script
    for name, surface in {
        "node-core-tests": "terminal", "node-widget-tests-1": "terminal",
        "node-widget-tests-2a": "terminal", "node-widget-tests-2b": "terminal",
        "node-widget-tests-3": "terminal", "rust-ticks-tests": "rust",
        "electron-desktop-suite": "desktop",
    }.items():
        assert jobs[name]["needs"] == "changed-surfaces"
        assert f"needs.changed-surfaces.outputs.{surface} == 'true'" in jobs[name]["if"]
        assert "github.event.pull_request.draft != true" in jobs[name]["if"]
        assert surface in classifier["outputs"]


def test_browser_journeys_run_inside_a_terminal_lane():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    assert "terminal-e2e-infra-self-tests" not in jobs
    runs = "\n".join(step.get("run", "") for step in jobs["node-widget-tests-3"]["steps"])
    for required in ("e2e:infra:typecheck", "e2e:infra:lint", "playwright install --with-deps chromium",
                     "e2e/infra-self-tests.spec.ts", "e2e/workspace-lifecycle.spec.ts", "e2e:public-demo"):
        assert required in runs


def _python_lanes(jobs: dict) -> dict[str, dict]:
    return {"python-tests": jobs["python-tests"], "python-shards": jobs["python-shards"]}


def test_python_lanes_classify_without_waiting_on_another_job():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    classifier_script = _classify_script(jobs["changed-surfaces"])
    for name, job in _python_lanes(jobs).items():
        assert "needs" not in job, f"{name} must queue as soon as the run starts"
        assert "github.event.pull_request.draft != true" in job["if"]
        checkout = job["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["fetch-depth"] == 0
        assert _classify_script(job) == classifier_script
        selected = "steps.classify.outputs.python == 'true'"
        for step in job["steps"]:
            if step.get("run", "").startswith("uv ") or "pytest packages/" in step.get("run", ""):
                assert selected in step["if"], f"{name}: {step} must only run when Python is selected"


def test_required_python_context_retains_all_packages_and_root_invariants():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    invariants = jobs["python-invariants"]
    assert "changed-surfaces" not in str(invariants.get("if", ""))
    runs = "\n".join(step.get("run", "") for step in invariants["steps"])
    assert "pytest tests/ scripts/__tests__/" in runs
    assert "ruff check packages/ tests/" in runs
    assert "--offline --days 0" in runs
    shards = jobs["python-shards"]
    assert shards["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert shards["strategy"]["fail-fast"] is False
    aggregate = jobs["python-tests"]
    assert "continue-on-error" not in aggregate
    assert "strategy" not in aggregate
    indices = []
    for job in (aggregate, shards):
        run = next(step["run"] for step in job["steps"] if step.get("name") == "Run Python package shard")
        for required in ("python -m pytest packages/*/*/tests/", "-p scripts.pytest_shard", "--ft-shard-count=5",
                         "--ft-shard-durations=scripts/pytest_shard_durations.json",
                         "--timeout=60", "--timeout-method=thread"):
            assert required in run
        assert "--ignore" not in run and " -k " not in run and " -m " not in run.replace("python -m pytest", "pytest")
        indices.append(run.split("--ft-shard-index=")[1].split()[0])
    # python-tests runs shard 0; the matrix covers the rest, so together they
    # cover every index from 0 to count - 1 exactly once.
    assert indices == ["0", "${{"]
    assert sorted([0, *shards["strategy"]["matrix"]["shard"]]) == list(range(5))
    assert (_REPO_ROOT / "scripts" / "pytest_shard_durations.json").is_file()


def test_required_python_context_waits_for_every_sibling_lane():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    aggregate = jobs["python-tests"]
    assert aggregate["permissions"] == {"contents": "read", "actions": "read"}
    step = next(step for step in aggregate["steps"] if step.get("name") == "Require every Python check in this run")
    assert step["if"] == "always()"
    assert aggregate["steps"][-1] is step
    run = step["run"]
    assert "scripts/ci_require_jobs.py" in run
    expected = ["python-invariants"] + [f"python-shards ({index})" for index in jobs["python-shards"]["strategy"]["matrix"]["shard"]]
    for name in expected:
        assert f"--job {name}" in run or f'--job "{name}"' in run
    assert "true|false) ;;" in run and "exit 1" in run


def test_python_workers_do_not_multiply_native_numerical_threads():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    from scripts.ft import PYTEST_NATIVE_THREAD_ENV

    assert len(PYTEST_NATIVE_THREAD_ENV) == 5
    assert set(PYTEST_NATIVE_THREAD_ENV.values()) == {"1"}
    for name in ("python-invariants", "python-shards", "python-tests"):
        assert jobs[name]["env"] == PYTEST_NATIVE_THREAD_ENV
    nightly = yaml.safe_load((_WORKFLOW_PATH.parent / "nightly-cross-platform.yml").read_text(encoding="utf-8"))
    assert all(nightly["env"].get(name) == value for name, value in PYTEST_NATIVE_THREAD_ENV.items())


@pytest.mark.parametrize("workflow", ["test.yml", "supply-chain.yml", "visual-a11y.yml"])
def test_protected_branch_runs_are_never_cancelled_by_a_newer_push(workflow):
    document = yaml.safe_load((_WORKFLOW_PATH.parent / workflow).read_text(encoding="utf-8"))
    assert document["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_required_electron_context_runs_on_every_pull_request():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    gate = jobs["electron-desktop-tests"]
    assert "name" not in gate
    assert set(gate["needs"]) == {"changed-surfaces", "electron-desktop-suite"}
    assert gate["if"] == "always() && github.event.pull_request.draft != true"
    assert "continue-on-error" not in gate
    assert [name for name, job in jobs.items() if job.get("name") == "electron-desktop-tests"] == []


@pytest.mark.parametrize("selected,suite,classification,expected", [
    ("true", "success", "success", 0),
    ("false", "skipped", "success", 0),
    ("true", "failure", "success", 1),
    ("true", "cancelled", "success", 1),
    ("true", "skipped", "success", 1),
    ("false", "success", "success", 1),
    ("false", "skipped", "failure", 1),
    ("", "skipped", "success", 1),
])
def test_electron_summary_propagates_every_suite_failure(selected, suite, classification, expected):
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    step = jobs["electron-desktop-tests"]["steps"][0]
    script = textwrap.dedent("\n".join(step["run"].splitlines()[1:-1]))
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False,
        env=os.environ | {"DESKTOP_REQUIRED": selected, "SUITE_RESULT": suite,
                          "CLASSIFIER_RESULT": classification},
    )
    assert result.returncode == expected, result.stdout + result.stderr
