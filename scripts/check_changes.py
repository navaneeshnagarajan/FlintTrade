"""Share conservative affected-surface selection between local checks and CI."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
SURFACES = ("code", "python", "terminal", "desktop", "rust", "site", "docs", "dependencies")
_INERT = {".gitignore", ".gitattributes", ".editorconfig", ".github/workflows/status-report.yml"}
_DEPENDENCY_NAMES = {
    "pyproject.toml", "package.json", "Cargo.toml", "Cargo.lock", "uv.lock", "pnpm-lock.yaml",
    "pnpm-workspace.yaml", "requirements.lock", "requirements.txt", "brokers.lock",
    ".npmrc", ".pnpmfile.cjs", "pnpmfile.cjs", "uv.toml", "rust-toolchain", "rust-toolchain.toml",
    ".python-version", ".node-version", ".nvmrc",
}
_PYTHON_PACKAGES = {
    "core/core", "core/data", "core/historical", "core/indicators", "core/ticks",
    "services/ai", "services/automation", "services/backtest", "services/ditto", "services/engine",
    "services/journal", "services/screener", "integrations/gateway", "integrations/webhooks",
}
_DOCUMENTATION_PACKAGES = _PYTHON_PACKAGES | {"apps/terminal", "apps/desktop", "apps/site", "core/design-system"}
_TERMINAL_CONTRACT_INPUTS = {
    "docs/INVENTORY.md", "packages/apps/site/src/app/globals.css",
}


def classify_paths(paths: Sequence[str], *, full: bool = False) -> dict[str, bool]:
    """Select the union of checks, expanding unknown or shared changes to all.

    ``python`` selects the package suites; repository invariants run separately
    even for documentation and frontend changes. This is deliberately a surface
    map, not a claim of a complete dependency graph between Python packages.
    """
    result = dict.fromkeys(SURFACES, full)
    if full:
        return result

    def select(*surfaces: str) -> None:
        for surface in surfaces:
            result[surface] = True

    for path in paths:
        parts = PurePosixPath(path).parts
        if not parts or path.startswith(("/", "\\")) or ".." in parts or "\\" in path:
            return dict.fromkeys(SURFACES, True)
        if path in _TERMINAL_CONTRACT_INPUTS:
            # Terminal source contracts also inspect the shared catalogue and
            # the site's design-system imports.
            select("python", "terminal", "site")
        if path in _INERT or path.startswith((".local/", ".github/ISSUE_TEMPLATE/")):
            if path.startswith(".github/workflows/"):
                select("dependencies")
            continue
        if path in {"notice", "notice.generated", "LICENSE"}:
            select("dependencies", "site")
            continue
        if parts[-1] in _DEPENDENCY_NAMES or ".cargo" in parts:
            return dict.fromkeys(SURFACES, True)
        # Package Markdown can be runtime input (AI skills, prompts and test
        # fixtures). Only a known package's root README is documentation.
        package_readme = (
            len(parts) == 4 and parts[-1] == "README.md"
            and "/".join(parts[1:3]) in _DOCUMENTATION_PACKAGES
        )
        if path.startswith(("docs/", "flinttrade-design/")) or (
            path.endswith(".md") and (parts[0] != "packages" or package_readme)
        ):
            select("docs", "site")
            continue
        if path.startswith("packages/apps/site/"):
            select("docs", "site")
            continue
        if path.startswith("packages/apps/terminal/"):
            # Python contracts inspect terminal API clients and fixtures.
            select("code", "python", "terminal", "site")
            continue
        if path.startswith("packages/apps/desktop/"):
            # Desktop bootstrap helpers and their subprocess tests are Python.
            select("code", "python", "desktop", "site")
            # Packaged install resources participate in frozen-install and
            # provenance assurance, even when the lockfiles do not change.
            if path.startswith(("packages/apps/desktop/resources/", "packages/apps/desktop/scripts/")):
                select("dependencies")
            continue
        if path.startswith("packages/core/design-system/"):
            select("code", "python", "terminal", "site")
            continue
        if len(parts) >= 4 and parts[0] == "packages" and "/".join(parts[1:3]) in _PYTHON_PACKAGES:
            package = "/".join(parts[1:3])
            select("code", "python")
            if package == "core/ticks":
                select("rust")
            if package in {"core/core", "integrations/gateway", "services/engine"}:
                select("terminal", "site")
            if package == "services/ai":
                select("site")
            continue
        # Root tests, configuration, CI, install scripts and new packages can
        # affect contracts across languages; a guess here could hide a failure.
        return dict.fromkeys(SURFACES, True)
    return result


def changed_paths(
    base: str = "origin/main", head: str = "HEAD", *, include_worktree: bool = False, root: Path = REPO_ROOT,
) -> list[str] | None:
    """Read changed paths, including both sides of renames; None selects all.

    The PR merge-base range includes every change on the branch. Local checks
    optionally include staged, unstaged and non-ignored untracked files too.
    Git arguments are never interpreted by a shell.
    """
    if not base or not head or base.startswith("-") or head.startswith("-"):
        return None

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, timeout=30,
        ).stdout

    try:
        base_sha = git("rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
        head_sha = git("rev-parse", "--verify", f"{head}^{{commit}}").decode().strip()
        names = git("diff", "--no-renames", "--name-only", "-z", f"{base_sha}...{head_sha}")
        if include_worktree:
            # Read index and working-copy changes independently: an unstaged
            # restoration can otherwise hide a change waiting in the index.
            names += git("diff", "--cached", "--no-renames", "--name-only", "-z", head_sha)
            names += git("diff", "--no-renames", "--name-only", "-z")
            names += git("ls-files", "--others", "--exclude-standard", "-z")
        return sorted({name.decode("utf-8", errors="surrogateescape") for name in names.split(b"\0") if name})
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def main(argv: Sequence[str] | None = None) -> int:
    """Print the check plan and optionally expose booleans to GitHub Actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args(argv)
    paths = [] if args.full else changed_paths(args.base, args.head)
    surfaces = classify_paths(paths or [], full=args.full or paths is None)
    print(json.dumps(surfaces, sort_keys=True))
    if args.github_output:
        output = os.environ.get("GITHUB_OUTPUT")
        if not output:
            parser.error("--github-output requires GITHUB_OUTPUT")
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.writelines(f"{key}={str(value).lower()}\n" for key, value in surfaces.items())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
