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

def test_classifier_outputs_reach_each_required_surface():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    classifier = jobs["changed-surfaces"]
    script = next(step["run"] for step in classifier["steps"] if step.get("id") == "classify")
    assert "scripts/check_changes.py" in script
    assert "--full --github-output" in script
    for name, surface in {
        "node-core-tests": "terminal", "node-widget-tests-1": "terminal",
        "node-widget-tests-2a": "terminal", "node-widget-tests-2b": "terminal",
        "node-widget-tests-3": "terminal", "rust-ticks-tests": "rust",
        "electron-desktop-tests": "desktop", "terminal-e2e-infra-self-tests": "terminal",
        "python-shards": "python",
    }.items():
        assert jobs[name]["needs"] == "changed-surfaces"
        assert f"needs.changed-surfaces.outputs.{surface} == 'true'" in jobs[name]["if"]
        assert "github.event.pull_request.draft != true" in jobs[name]["if"]
        assert surface in classifier["outputs"]


def test_required_python_context_retains_all_packages_and_root_invariants():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    aggregate = jobs["python-tests"]
    assert set(aggregate["needs"]) == {"changed-surfaces", "python-invariants", "python-shards"}
    assert "always()" in aggregate["if"]
    assert "continue-on-error" not in aggregate
    invariants = jobs["python-invariants"]
    assert "changed-surfaces" not in str(invariants.get("if", ""))
    runs = "\n".join(step.get("run", "") for step in invariants["steps"])
    assert "pytest tests/ scripts/__tests__/" in runs
    assert "ruff check packages/ tests/" in runs
    assert "--offline --days 0" in runs
    shards = jobs["python-shards"]
    assert shards["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    assert shards["strategy"]["fail-fast"] is False
    run = next(step["run"] for step in shards["steps"] if step.get("name") == "Run Python package shard")
    for required in ("python -m pytest packages/*/*/tests/", "-p scripts.pytest_shard", "--ft-shard-count=4",
                     "--ft-shard-index=${{ matrix.shard }}", "--timeout=60", "--timeout-method=thread"):
        assert required in run
    assert "--ignore" not in run and " -k " not in run and " -m " not in run.replace("python -m pytest", "pytest")


def test_python_workers_do_not_multiply_native_numerical_threads():
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    from scripts.ft import PYTEST_NATIVE_THREAD_ENV

    assert len(PYTEST_NATIVE_THREAD_ENV) == 5
    assert set(PYTEST_NATIVE_THREAD_ENV.values()) == {"1"}
    for name in ("python-invariants", "python-shards"):
        assert jobs[name]["env"] == PYTEST_NATIVE_THREAD_ENV
    nightly = yaml.safe_load((_WORKFLOW_PATH.parent / "nightly-cross-platform.yml").read_text(encoding="utf-8"))
    assert all(nightly["env"].get(name) == value for name, value in PYTEST_NATIVE_THREAD_ENV.items())


@pytest.mark.parametrize("selected,invariants,shards,classification,expected", [
    ("true", "success", "success", "success", 0),
    ("false", "success", "skipped", "success", 0),
    ("true", "success", "failure", "success", 1),
    ("true", "success", "cancelled", "success", 1),
    ("true", "success", "skipped", "success", 1),
    ("true", "failure", "success", "success", 1),
    ("false", "failure", "skipped", "success", 1),
    ("true", "skipped", "success", "success", 1),
    ("false", "success", "skipped", "failure", 1),
    ("", "success", "skipped", "success", 1),
    ("false", "success", "success", "success", 1),
])
def test_actual_python_summary_propagates_every_required_failure(selected, invariants, shards, classification, expected):
    jobs = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]
    step = jobs["python-tests"]["steps"][0]
    script = textwrap.dedent("\n".join(step["run"].splitlines()[1:-1]))
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False,
        env=os.environ | {"PYTHON_REQUIRED": selected, "INVARIANTS_RESULT": invariants,
                          "SHARDS_RESULT": shards, "CLASSIFIER_RESULT": classification},
    )
    assert result.returncode == expected, result.stdout + result.stderr
