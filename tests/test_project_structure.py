"""Sanity checks on the public-repo structure.

Asserts that the files and directories every consumer of FlintTrade expects
are present after a clone. Does not exercise application behaviour — that
lives under each package's tests/ folder.
"""

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# All 16 packages currently tracked under packages/.
# Keep this list aligned with templates/package-purposes.yml and flint.toml.
PACKAGES = [
    "ai",
    "automation",
    "backtest-engine",
    "chrome-extension",
    "core",
    "data",
    "desktop",
    "ditto",
    "engine",
    "gateway",
    "historical",
    "indicators",
    "integration",
    "screener",
    "terminal",
    "tick-engine",
]

# Files every fresh clone must have at the repo root for the project to make
# sense to a contributor or user. CLAUDE.md / AGENTS.md / PLAN.md are
# intentionally absent — they were moved to templates/agent-context/ during
# the public-repo modernisation pass and are scaffolded per-machine via
# scripts/setup-agent-context.sh.
REQUIRED_ROOT_FILES = [
    "README.md",
    "VERSION",
    "LICENSE",
    "NOTICE",
    ".gitignore",
    ".env.example",
    "flint.toml",
    "Makefile",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
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
        d = os.path.join(ROOT, "packages", pkg)
        assert os.path.isdir(d), f"Missing package directory: {pkg}"
        assert os.path.exists(
            os.path.join(d, "README.md")
        ), f"Missing per-package README: {pkg}/README.md"


def test_version():
    with open(os.path.join(ROOT, "VERSION")) as f:
        v = f.read().strip()
    # Strip pre-release suffix (-dev, -alpha, -beta, -rc.N) then check 3-part semver.
    base = v.split("-")[0]
    assert len(base.split(".")) == 3, f"VERSION is not 3-part semver: {v!r}"


def test_no_tracked_agent_internal_files():
    """CLAUDE.md / AGENTS.md / PLAN.md must not be tracked at the repo root."""
    for f in ["CLAUDE.md", "AGENTS.md", "PLAN.md"]:
        assert not is_tracked(f), f"{f} should be gitignored — tracked at repo root"


def test_no_tracked_per_package_agent_files():
    """packages/<pkg>/CLAUDE.md and AGENTS.md must not exist after the move."""
    for pkg in PACKAGES:
        for f in ["CLAUDE.md", "AGENTS.md"]:
            path = os.path.join("packages", pkg, f)
            assert not is_tracked(path), f"{path} should be gitignored — tracked in git"


def test_agent_context_templates_present():
    """The tracked template tree that scripts/setup-agent-context.sh reads."""
    assert os.path.isdir(
        os.path.join(ROOT, "templates", "agent-context")
    ), "Missing templates/agent-context/"
    for f in ["CLAUDE.md.template", "AGENTS.md.template", "PLAN.md.template"]:
        assert os.path.exists(
            os.path.join(ROOT, "templates", "agent-context", f)
        ), f"Missing templates/agent-context/{f}"
    for pkg in PACKAGES:
        for f in ["CLAUDE.md.template", "AGENTS.md.template"]:
            assert os.path.exists(
                os.path.join(ROOT, "templates", "agent-context", "packages", pkg, f)
            ), f"Missing templates/agent-context/packages/{pkg}/{f}"
