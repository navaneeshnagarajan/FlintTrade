"""Selection preserves dependent checks and falls back to the full gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_changes import SURFACES, changed_paths, classify_paths

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


@pytest.mark.parametrize("path", ["README.md", "docs/setup.md", "packages/apps/site/app/page.tsx"])
def test_docs_and_site_keep_invariants_without_package_suites(path: str) -> None:
    result = classify_paths([path])
    assert result["docs"] and result["site"]
    assert not any(result[key] for key in ("code", "python", "terminal", "desktop", "rust", "dependencies"))


@pytest.mark.parametrize("path", [
    ".local/example", "notice", "LICENSE", ".gitignore", ".gitattributes", ".editorconfig",
    ".github/workflows/status-report.yml", ".github/ISSUE_TEMPLATE/config.yml",
])
def test_previous_inert_paths_stay_non_code_but_licence_checks_run(path: str) -> None:
    result = classify_paths([path])
    assert not result["code"]
    assert not any(result[key] for key in ("python", "terminal", "desktop", "rust"))
    if path in ("notice", "LICENSE"):
        assert result["dependencies"]


@pytest.mark.parametrize("path", [
    "new-unknown.file", "pyproject.toml", "uv.lock", "pnpm-lock.yaml", "package.json",
    "scripts/ft.py", "infra/scripts/install.sh", "tests/conftest.py", "conftest.py",
    ".github/workflows/test.yml", "packages/services/ai/pyproject.toml",
    "packages/core/ticks/.cargo/audit.toml", "packages/core/ticks/.cargo/config.toml",
    "packages/core/ticks/rust-toolchain.toml", "packages/apps/terminal/.npmrc",
])
def test_uncertain_or_shared_changes_run_every_surface(path: str) -> None:
    assert all(classify_paths([path]).values())


def test_known_python_leaf_does_not_build_unrelated_apps() -> None:
    result = classify_paths(["packages/services/journal/src/models.py"])
    assert result["python"] and result["code"]
    assert not any(result[key] for key in ("terminal", "desktop", "rust", "site", "dependencies"))


@pytest.mark.parametrize("group", ["core/core", "integrations/gateway", "services/engine"])
def test_api_and_trading_python_changes_keep_terminal_contracts(group: str) -> None:
    result = classify_paths([f"packages/{group}/src/route.py"])
    assert result["python"] and result["terminal"]


def test_terminal_change_keeps_site_contracts_and_repository_guards() -> None:
    result = classify_paths(["packages/apps/terminal/src/widgets/orders/OrderPad.tsx"])
    assert result["terminal"] and result["site"] and result["code"]
    assert result["python"]


@pytest.mark.parametrize("path", [
    "packages/apps/terminal/src/services/api.ts",
    "packages/apps/terminal/src/__tests__/fixtures/positions.json",
    "packages/apps/desktop/resources/bootstrap/flinttrade-safe-rmtree.py",
    "packages/apps/desktop/tests/test_desktop_backend.py",
    "packages/services/ai/skills/order_safety.md",
    "packages/services/ai/tests/fixtures/prompt.md",
])
def test_runtime_inputs_keep_the_python_contract_and_bootstrap_suites(path: str) -> None:
    assert classify_paths([path])["python"]


def test_package_readme_remains_documentation() -> None:
    result = classify_paths(["packages/services/ai/README.md"])
    assert result["docs"] and result["site"]
    assert not result["python"]


@pytest.mark.parametrize("path", [
    "packages/services/ai/skills/README.md",
    "packages/services/ai/tests/fixtures/README.md",
    "packages/apps/terminal/src/README.md",
])
def test_nested_readme_keeps_runtime_and_source_contract_checks(path: str) -> None:
    assert classify_paths([path])["python"]


def test_nested_desktop_resource_readme_keeps_packaging_and_install_assurance() -> None:
    result = classify_paths(["packages/apps/desktop/resources/README.md"])
    assert result["python"] and result["desktop"] and result["dependencies"]


def test_unknown_package_readme_does_not_bypass_the_full_fallback() -> None:
    assert all(classify_paths(["packages/services/new-package/README.md"]).values())


@pytest.mark.parametrize("path", ["notice", "notice.generated", "LICENSE",
                                  "packages/services/ai/src/flinttrade_ai/mcp_bridge.py"])
def test_site_attribution_and_mcp_contracts_keep_the_site_gate(path: str) -> None:
    assert classify_paths([path])["site"]


@pytest.mark.parametrize("path", ["docs/INVENTORY.md", "packages/apps/site/src/app/globals.css"])
def test_terminal_source_contracts_keep_their_cross_surface_inputs(path: str) -> None:
    result = classify_paths([path])
    assert result["terminal"] and result["python"] and result["site"]


def test_design_system_reaches_both_consuming_apps() -> None:
    result = classify_paths(["packages/core/design-system/src/button.tsx"])
    assert result["terminal"] and result["site"]


def test_rust_keeps_python_binding_checks() -> None:
    result = classify_paths(["packages/core/ticks/src/lib.rs"])
    assert result["rust"] and result["python"]


def test_mixed_change_uses_the_union_and_full_override_is_exhaustive() -> None:
    paths = ["README.md", "packages/services/journal/src/models.py", "packages/apps/desktop/electron/main.ts"]
    result = classify_paths(paths)
    assert result["docs"] and result["site"] and result["python"] and result["desktop"]
    assert all(classify_paths(paths, full=True).values())
    assert set(classify_paths([])) == set(SURFACES)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "old.py").write_text("# old\n", encoding="utf-8")
    _git(tmp_path, "add", "old.py")
    _git(tmp_path, "commit", "-m", "baseline")
    _git(tmp_path, "branch", "base")
    return tmp_path


def test_git_selection_includes_both_sides_of_rename_and_deletion(repository: Path) -> None:
    _git(repository, "mv", "old.py", "renamed.md")
    _git(repository, "commit", "-m", "rename")
    assert set(changed_paths("base", root=repository) or []) == {"old.py", "renamed.md"}
    _git(repository, "rm", "renamed.md")
    _git(repository, "commit", "-m", "delete")
    assert "old.py" in (changed_paths("base", root=repository) or [])


def test_local_selection_includes_staged_unstaged_and_untracked(repository: Path) -> None:
    (repository / "staged.md").write_text("staged", encoding="utf-8")
    _git(repository, "add", "staged.md")
    (repository / "old.py").write_text("unstaged", encoding="utf-8")
    (repository / "untracked.ts").write_text("new", encoding="utf-8")
    assert set(changed_paths("base", include_worktree=True, root=repository) or []) == {
        "staged.md", "old.py", "untracked.ts",
    }


def test_unstaged_restoration_cannot_hide_a_staged_change(repository: Path) -> None:
    original = (repository / "old.py").read_text(encoding="utf-8")
    (repository / "old.py").write_text("# staged change\n", encoding="utf-8")
    _git(repository, "add", "old.py")
    (repository / "old.py").write_text(original, encoding="utf-8")
    assert _git(repository, "diff", "HEAD", "--name-only") == ""
    assert changed_paths("base", include_worktree=True, root=repository) == ["old.py"]


def test_missing_base_returns_full_fallback(repository: Path) -> None:
    assert changed_paths("missing", root=repository) is None
    assert changed_paths("--help", root=repository) is None


def test_cli_unknown_base_writes_all_github_outputs(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_changes.py"), "--base", "unknown-base", "--github-output"],
        env=os.environ | {"GITHUB_OUTPUT": str(output)}, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert all(json.loads(result.stdout).values())
    assert set(output.read_text(encoding="utf-8").splitlines()) == {f"{key}=true" for key in SURFACES}
