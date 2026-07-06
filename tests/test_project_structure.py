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
# sense to a contributor or user. As of the public-repo policy
# (see memory feedback_public_repos_ci_policy / commit bc7f5374), the
# contributor-facing CLAUDE.md / AGENTS.md / PLAN.md are TRACKED at the root so
# every human or agent picking up the repo gets the same in-repo guidance; the
# templates/agent-context/ tree remains for per-package scaffolding.
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
    "CLAUDE.md",
    "AGENTS.md",
    "PLAN.md",
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


def test_agent_guidance_files_tracked_at_root():
    """CLAUDE.md / AGENTS.md / PLAN.md are tracked at the repo root.

    Per the public-repo policy (every repo is public and open for
    contributions), the in-repo guidance files are the single source of truth
    for how any human or agent works on the repo and must travel with a clone.
    """
    for f in ["CLAUDE.md", "AGENTS.md", "PLAN.md"]:
        assert is_tracked(f), f"{f} must be tracked at the repo root for contributors"


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
