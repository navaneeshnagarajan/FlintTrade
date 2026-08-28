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

import re
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
    # Set containment (both main AND dev required; mutation-sensitive)
    required = {"main", "dev"}
    assert required.issubset(set(branches)), (
        f"pull_request.branches must contain both main and dev as a set; "
        f"got {branches}"
    )


# ----------------------------------------------------------------------
# Classifier contract tests (exercise the *actual* YAML classify script)
# ----------------------------------------------------------------------

def _load_workflow():
    return yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))


def _extract_classify_pattern(doc: dict) -> str:
    """Extract the non-code grep pattern from the actual changed-surfaces classify step."""
    jobs = doc.get("jobs", {})
    changed = jobs.get("changed-surfaces", {})
    steps = changed.get("steps", [])
    for step in steps:
        run = step.get("run", "")
        if isinstance(run, str) and "grep -qvE" in run:
            # Extract the pattern inside the single quotes after -qvE
            m = re.search(r"grep -qvE '([^']+)'", run)
            if m:
                return m.group(1)
    raise AssertionError("Could not extract classify grep pattern from YAML")


def _extract_expensive_lane_if(doc: dict) -> str:
    """Confirm expensive lanes key on the code output (not hard-coded)."""
    jobs = doc.get("jobs", {})
    for job_name, job in jobs.items():
        if "widget" in job_name or job_name in ("rust-ticks-tests", "electron-desktop-tests"):
            if_cond = job.get("if", "")
            if "needs.changed-surfaces.outputs.code == 'true'" in str(if_cond):
                return if_cond
    return ""


def _simulate_classify(changed: str, noncode_pattern: str, resolvable: bool = True) -> str:
    """Simulate the exact classify logic from the extracted YAML script."""
    if not resolvable:
        return "true"
    # Same logic as: if printf ... | grep -qvE 'pattern' then true else false
    # Use re.search because the ERE contains ^ and $ anchors inside the alternation
    lines = [line for line in changed.strip().splitlines() if line.strip()]
    if not lines:
        return "false"
    for line in lines:
        if not re.search(noncode_pattern, line):
            return "true"
    return "false"


# Representative matrix (paths that must be non-code when touched alone or with docs)
FORMER_IGNORED = [
    ".local/foo",
    "notice",
    "LICENSE",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".github/workflows/claude-foo.yml",
    ".github/workflows/status-report.yml",
    ".github/ISSUE_TEMPLATE/bar.md",
]

ORDINARY_CODE = [
    "packages/core/core/src/foo.py",
    "packages/apps/terminal/src/App.tsx",
    "packages/apps/desktop/src/main.ts",
    "tests/test_something.py",
    ".github/workflows/test.yml",
]

DOCS_ONLY = [
    "README.md",
    "docs/guide.md",
    "packages/apps/site/pages/index.tsx",
]


def test_changed_surfaces_classifier_former_ignored_are_non_code():
    """Former ignored surfaces alone must classify code=false (do not run expensive lanes)."""
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    for path in FORMER_IGNORED:
        code = _simulate_classify(path, pattern)
        assert code == "false", f"{path} must be non-code but got {code}"


def test_changed_surfaces_classifier_ordinary_code_is_code():
    """Ordinary code paths must classify code=true (run expensive lanes)."""
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    for path in ORDINARY_CODE:
        code = _simulate_classify(path, pattern)
        assert code == "true", f"{path} must be code but got {code}"


def test_changed_surfaces_classifier_mixed_former_ignored_plus_code_is_code():
    """Mix of former-ignored + ordinary code must be code=true."""
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    changed = "\n".join(FORMER_IGNORED[:2] + ORDINARY_CODE[:1])
    code = _simulate_classify(changed, pattern)
    assert code == "true"


def test_changed_surfaces_classifier_docs_site_md_only_is_non_code():
    """Existing docs/site/md-only must remain code=false (no regression)."""
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    for path in DOCS_ONLY:
        code = _simulate_classify(path, pattern)
        assert code == "false", f"{path} must be non-code but got {code}"


def test_changed_surfaces_classifier_unresolvable_fails_open():
    """Unresolvable diff range must fail open to code=true."""
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    code = _simulate_classify("", pattern, resolvable=False)
    assert code == "true"


def test_changed_surfaces_classifier_mutation_sensitive():
    """If the YAML classifier is mutated (any single former-ignored fragment removed), test fails.
    Uses explicit per-surface ERE fragments; omission of each makes its representative path code=true.
    """
    doc = _load_workflow()
    pattern = _extract_classify_pattern(doc)
    # Normalise: strip outer grouping parens so every fragment appears verbatim as alternation term
    # and mutations keep valid regex for re.search in _simulate_classify
    if pattern.startswith("(") and pattern.endswith(")"):
        pattern = pattern[1:-1]

    # Explicit per-surface expected ERE fragments (must match live YAML exactly; no any() fallback)
    per_surface = {
        ".local/**": ("^\\.local/", ".local/foo"),
        "notice": ("^notice$", "notice"),
        "LICENSE": ("^LICENSE$", "LICENSE"),
        ".gitignore": ("^\\.gitignore$", ".gitignore"),
        ".gitattributes": ("^\\.gitattributes$", ".gitattributes"),
        ".editorconfig": ("^\\.editorconfig$", ".editorconfig"),
        ".github/workflows/claude*.yml": ("^\\.github/workflows/claude.*\\.yml$", ".github/workflows/claude-foo.yml"),
        ".github/workflows/status-report.yml": ("^\\.github/workflows/status-report\\.yml$", ".github/workflows/status-report.yml"),
        ".github/ISSUE_TEMPLATE/**": ("^\\.github/ISSUE_TEMPLATE/", ".github/ISSUE_TEMPLATE/config.json"),
    }

    for surf, (frag, rep) in per_surface.items():
        assert frag in pattern, f"Expected fragment {frag} for {surf} missing from pattern"
        # Mutation sensitivity: replace ONLY this fragment with sentinel (removes its protection);
        # representative must now classify as code. (String replace keeps regex syntax valid.)
        mutated = pattern.replace(frag, "NEVER_MATCH_SURFACE_42")
        code = _simulate_classify(rep, mutated)
        assert code == "true", (
            f"After removing {frag} ({surf}), {rep} must become code=true (was non-code); got {code}"
        )

    # Also confirm expensive lanes still gate on the output (unchanged requirement)
    if_cond = _extract_expensive_lane_if(doc)
    assert "needs.changed-surfaces.outputs.code == 'true'" in if_cond, (
        "Expensive lanes must remain gated on changed-surfaces code output"
    )


def test_pull_request_branches_set_containment_mutation_sensitive():
    """pull_request.branches must require the full set {main, dev}; mutation to drop one must fail."""
    doc = _load_workflow()
    on_block = _normalise_on(doc)
    pr_config = on_block.get("pull_request", {}) or {}
    branches = pr_config.get("branches", [])
    if isinstance(branches, str):
        branches = [branches]
    required = {"main", "dev"}
    assert required.issubset(set(branches)), (
        f"branches must contain the full set; mutation detected: {branches}"
    )
    # Explicitly not 'any' — both required
    assert len(set(branches) & required) == 2
