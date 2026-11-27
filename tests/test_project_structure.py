"""Sanity checks on the public-repo structure.

Asserts that the files and directories every consumer of FlintTrade expects
are present after a clone. Does not exercise application behaviour — that
lives under each package's tests/ folder.
"""

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# All post-restructure packages tracked under packages/{core,services,integrations,apps}/.
# Keep this list aligned with templates/package-purposes.yml and flint.toml.
PACKAGES = [
    "apps/desktop",
    "apps/site",
    "apps/terminal",
    "core/core",
    "core/data",
    "core/design-system",
    "core/historical",
    "core/indicators",
    "core/ticks",
    "services/engine",
    "services/screener",
    "services/backtest",
    "services/ai",
    "services/ditto",
    "services/automation",
    "services/journal",
    "integrations/gateway",
    "integrations/webhooks",
]

# Files every fresh clone must have at the repo root for the project to make
# sense to a contributor or user.
REQUIRED_ROOT_FILES = [
    "readme.md",
    "VERSION",
    "LICENSE",
    "notice",
    ".gitignore",
    ".env.example",
    "flint.toml",
    "Makefile",
    "contributing.md",
    "changelog.md",
    "code-of-conduct.md",
    "security.md",
    "PLAN.md",
    "ROADMAP.md",
    "RETICLE.md",
]


def is_tracked(path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def test_root_files():
    for f in REQUIRED_ROOT_FILES:
        assert os.path.exists(os.path.join(ROOT, f)), f"Missing: {f}"


def test_packages():
    for pkg in PACKAGES:
        d = os.path.join(ROOT, "packages", *pkg.split("/"))
        assert os.path.isdir(d), f"Missing package directory: {pkg}"
        assert os.path.exists(
            os.path.join(d, "README.md")
        ), f"Missing per-package README: {pkg}/README.md"


def test_version():
    with open(os.path.join(ROOT, "VERSION")) as f:
        v = f.read().strip()
    # Strip pre-release suffix (-dev, -alpha, -beta, -rc.N) then check 3-part semver.
    base = v.removeprefix("v").split("-")[0]
    assert len(base.split(".")) == 3, f"VERSION is not 3-part semver: {v!r}"


# These paths must not be tracked in the public repository.
UNTRACKED_TOOLING_PATHS = [
    "AGENTS.md",
    "CLAUDE.md",
    ".cursor",
    "templates/agent-context",
    "scripts/setup-agent-context.sh",
]


def test_removed_tooling_files_are_not_tracked():
    for path in UNTRACKED_TOOLING_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--", path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout == "", f"{path} must stay untracked"


def test_no_tracked_per_package_agent_files():
    """packages/<pkg>/CLAUDE.md and AGENTS.md stay untracked."""
    for pkg in PACKAGES:
        for f in ["CLAUDE.md", "AGENTS.md"]:
            path = os.path.join("packages", pkg, f)
            assert not is_tracked(path), f"{path} should be gitignored — tracked in git"
