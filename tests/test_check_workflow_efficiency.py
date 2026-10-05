"""Auxiliary check selection preserves assurance while avoiding unrelated PR work."""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
DEPENDENCY_JOBS = ("python-audit", "rust-audit", "node-audit", "transitive-licences")


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    return document.get("on", document.get(True, {}))


def _classifier():
    spec = importlib.util.spec_from_file_location("check_workflow_changes", ROOT / "scripts" / "check_changes.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_supply_chain_has_full_main_scheduled_and_manual_assurance() -> None:
    """A scoped PR cannot remove exhaustive assurance for the protected branches."""
    workflow = _workflow("supply-chain.yml")
    triggers = _triggers(workflow)
    assert {"schedule", "workflow_dispatch", "push", "pull_request"} <= triggers.keys()
    for event in ("push", "pull_request"):
        assert {"main", "dev"} <= set(triggers[event]["branches"])
        assert not {"paths", "paths-ignore"} & triggers[event].keys()

    changed = workflow["jobs"]["changed-surfaces"]
    assert changed["outputs"]["dependencies"] == "${{ steps.classify.outputs.dependencies }}"
    steps = changed["steps"]
    assert any(step.get("with", {}).get("fetch-depth") == 0 for step in steps)
    classify = next(step for step in steps if step.get("id") == "classify")
    assert classify["env"]["FORCE_FULL"] == "${{ github.event_name != 'pull_request' }}"
    assert '"$FORCE_FULL" = "true"' in classify["run"]
    assert "scripts/check_changes.py --full --github-output" in classify["run"]
    assert 'scripts/check_changes.py --base "$BASE_SHA" --head "$HEAD_SHA" --github-output' in classify["run"]
    assert not classify.get("continue-on-error", False)

    for name in DEPENDENCY_JOBS:
        job = workflow["jobs"][name]
        assert job["needs"] == "changed-surfaces"
        assert "github.event.pull_request.draft != true" in job["if"]
        assert "needs.changed-surfaces.outputs.dependencies == 'true'" in job["if"]


def test_site_uses_the_same_selection_and_full_triggers_as_test() -> None:
    """Site contracts must run for every selected surface, including API changes."""
    main = _workflow("test.yml")
    caller = main["jobs"]["site"]
    assert caller["needs"] == "changed-surfaces"
    assert caller["uses"] == "./.github/workflows/site.yml"
    assert "needs.changed-surfaces.outputs.site == 'true'" in caller["if"]
    assert "github.event.pull_request.draft != true" in caller["if"]
    reusable = _workflow("site.yml")
    assert set(_triggers(reusable)) == {"workflow_call"}
    commands = "\n".join(step.get("run", "") for step in reusable["jobs"]["site"]["steps"])
    for script in ("typecheck", "test", "build"):
        assert f"pnpm --dir packages/apps/site run {script}" in commands
    assert "pnpm install --frozen-lockfile" in commands
    for path in ("README.md", "packages/core/core/src/routes.py", "packages/apps/desktop/electron/main.ts"):
        assert _classifier().classify_paths([path])["site"]


@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "brokers.lock",
        "requirements.lock",
        "broker-sdk-build.lock",
        "notice",
        "notice.generated",
        "LICENSE",
        "supply-chain/audit-tooling.lock",
        "scripts/new-installer.ps1",
        "infra/new-installer.sh",
        ".github/workflows/new-build.yml",
        "packages/apps/desktop/resources/new-bootstrap.sh",
        "packages/apps/desktop/resources/new-bootstrap.ps1",
        "unknown-new-install-path.sh",
    ],
)
def test_dependency_assurance_covers_locks_support_scripts_and_unknown_paths(path: str) -> None:
    """Changed assurance inputs and unfamiliar paths must select the audit jobs."""
    assert _classifier().classify_paths([path])["dependencies"] is True


def test_all_existing_install_guard_scan_paths_select_dependency_assurance() -> None:
    """Selection follows the real installation guard surfaces, including desktop resources."""
    classifier = _classifier()
    scanned: set[str] = set()
    for name in ("test_no_unhashed_pip_install.py", "test_pnpm_install_frozen.py"):
        tree = ast.parse((ROOT / "tests" / name).read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "_SCAN_GLOBS" for target in node.targets)
        )
        for pattern in ast.literal_eval(assignment.value):
            scanned.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob(pattern) if path.is_file())
    assert scanned, "Install guard coverage must not be vacuous"
    missing = [path for path in sorted(scanned) if not classifier.classify_paths([path])["dependencies"]]
    assert not missing, f"Install guard changes would skip dependency assurance: {missing}"


@pytest.mark.parametrize(
    "path",
    ["packages/core/core/src/safety.py", "packages/apps/terminal/src/components/Example.tsx", "docs/example.md"],
)
def test_ordinary_source_and_documentation_changes_avoid_dependency_audits(path: str) -> None:
    assert _classifier().classify_paths([path])["dependencies"] is False


def test_dependency_guards_and_audit_failure_semantics_are_preserved() -> None:
    jobs = _workflow("supply-chain.yml")["jobs"]
    for name in ("python-audit", "rust-audit", "node-audit"):
        assert not jobs[name].get("continue-on-error", False)
    python_commands = "\n".join(step.get("run", "") for step in jobs["python-audit"]["steps"])
    for guard in (
        "pip-audit-with-allowlist.py",
        "check-brokers-lock.py",
        "check-broker-sdk-licences.py",
        "generate-notice.py --check",
        "check-no-git-deps.py",
        "test_no_unhashed_pip_install.py",
        "test_pnpm_install_frozen.py",
        "check-uv-lock-export-drift.py",
    ):
        assert guard in python_commands
    assert "electron-package-verification" not in jobs


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("packages/apps/terminal/src/widgets/trading/OrderPad/OrderPad.tsx", True),
        ("packages/core/design-system/src/index.ts", True),
        ("packages/apps/terminal/e2e/visual/run-advisory.mjs", True),
        ("package.json", True),
        ("pnpm-lock.yaml", True),
        ("pnpm-workspace.yaml", True),
        (".github/workflows/visual-a11y.yml", True),
        ("packages/core/core/src/safety.py", False),
        ("docs/example.md", False),
    ],
)
def test_visual_workflow_selects_relevant_surfaces(path: str, expected: bool) -> None:
    triggers = _triggers(_workflow("visual-a11y.yml"))
    for event in ("push", "pull_request"):
        patterns = triggers[event]["paths"]
        assert any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns) is expected


def test_visual_drafts_skip_and_manual_baseline_refresh_requires_success() -> None:
    workflow = _workflow("visual-a11y.yml")
    assert "workflow_dispatch" in _triggers(workflow)
    job = workflow["jobs"]["terminal-visual-a11y"]
    assert job["if"] == "github.event.pull_request.draft != true"
    assert job["env"]["VISUAL_AXE_GATE"] == "0"
    commit = next(step for step in job["steps"] if step.get("name") == "Commit regenerated baselines")
    assert commit["if"] == "success() && github.event_name == 'workflow_dispatch' && inputs.update_baselines"


def test_dependabot_version_updates_are_staggered_without_disabling_security_updates() -> None:
    configuration = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = configuration["updates"]
    assert {entry["package-ecosystem"] for entry in updates} == {"github-actions", "npm", "uv", "cargo"}
    assert len({entry["schedule"]["day"] for entry in updates}) == len(updates)
    for entry in updates:
        assert entry["schedule"]["interval"] == "weekly"
        assert 0 < entry["open-pull-requests-limit"] <= 2
        assert entry.get("groups"), "Version update grouping must remain enabled"
        assert not entry.get("ignore"), "Queue reduction must not suppress dependency or security updates"
