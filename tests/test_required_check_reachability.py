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

    # The critical invariant: no top-level paths-ignore on the PR trigger.
    # (push may keep its own; job-level if: conditions remain for cost control.)
    assert "paths-ignore" not in pr_config, (
        "pull_request trigger must not contain paths-ignore; "
        "otherwise PRs that touch only ignored paths (e.g. .github/workflows/claude*.yml) "
        "skip the whole Test workflow and omit the required check contexts on main/dev."
    )

    # Sanity: still targets the protected branches
    branches = pr_config.get("branches", [])
    if isinstance(branches, str):
        branches = [branches]
    assert any(b in ("main", "dev") for b in branches), (
        "pull_request must still target main and/or dev"
    )
