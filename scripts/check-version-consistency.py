#!/usr/bin/env python3
"""Verify FlintTrade release version consistency across publishable surfaces."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACKAGE_JSONS = [
    "package.json",
    "packages/core/design-system/package.json",
    "packages/apps/terminal/package.json",
    "packages/apps/site/package.json",
    "packages/apps/desktop/package.json",
]

CARGO_MANIFESTS = [
    "packages/core/ticks/Cargo.toml",
    "packages/apps/desktop/src-tauri/Cargo.toml",
]

CURRENT_TAG_FILES = [
    "readme.md",
    "disclaimer.md",
    "CLAUDE.md",
    "PLAN.md",
    "docs/ARCHITECTURE.md",
    "docs/DESKTOP.md",
    "docs/INVENTORY.md",
    "docs/USER_GUIDE.md",
    "docs/setup/macos.md",
    "docs/setup/QUICKSTART.md",
    "docs/setup/windows.md",
    "packages/apps/site/src/app/page.tsx",
    "templates/agent-context/AGENTS.md.template",
    "templates/agent-context/CLAUDE.md.template",
    "templates/agent-context/PLAN.md.template",
]

INSTALLER_POLICY_FILES = [
    "readme.md",
    "docs/DESKTOP.md",
    "docs/setup/macos.md",
    "docs/setup/windows.md",
    "packages/apps/site/src/app/page.tsx",
    "Makefile",
    ".github/workflows/desktop-release.yml",
]

# Subsystems that no longer exist; docs describing the CURRENT system must not
# name them (LM Studio → managed Ollama; OpenClaw → agent_backends).
RETIRED_NAMES = ["OpenClaw", "LM Studio"]
RETIRED_NAME_FILES = [
    "security.md",
    "readme.md",
    "docs/DESKTOP.md",
    "docs/USER_GUIDE.md",
    "docs/ARCHITECTURE.md",
]

STALE_INSTALLER_PHRASES = [
    "`.dmg`, `.app`",
    "`.dmg` or `.app`",
    ".dmg or .app",
    ".dmg + .app",
    ".dmg/.app",
    "`.msi`, `.exe`",
    "`.msi` or `.exe`",
    ".exe or .msi",
    ".msi/.exe",
]

def _stale_current_pattern(version_tag: str) -> "re.Pattern[str] | None":
    """Pattern flagging sibling pre-releases of the current tag (e.g. an older beta).

    Derived from VERSION so a release bump cannot leave this check pinned to a
    previous tag. Stable (non-prerelease) versions have no sibling family.
    """
    match = re.match(r"^v(\d+\.\d+\.\d+-[A-Za-z]+)(?:\.(\d+))?$", version_tag)
    if not match:
        return None
    family = re.escape(match.group(1))
    suffix = match.group(2)
    if suffix is None:
        return re.compile(rf"\bv?{family}\.\d+\b")
    return re.compile(rf"\bv?{family}(?!\.{re.escape(suffix)}\b)\b")
SEMVER_WITH_PRERELEASE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")


def _read_json(path: str) -> object:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _read_toml(path: str) -> dict[str, object]:
    with (ROOT / path).open("rb") as handle:
        return tomllib.load(handle)


def _fail(failures: list[str], label: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    failures: list[str] = []

    version_tag = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not SEMVER_WITH_PRERELEASE.match(version_tag):
        failures.append(f"VERSION is not SemVer-like: {version_tag!r}")

    if not version_tag.startswith("v"):
        failures.append(f"VERSION must be a git tag with leading v: {version_tag!r}")

    bare_version = version_tag.removeprefix("v")
    release_note = f"docs/releases/{version_tag}.md"

    _fail(failures, "flint.toml project.version", _read_toml("flint.toml")["project"]["version"], version_tag)

    for path in PACKAGE_JSONS:
        package = _read_json(path)
        assert isinstance(package, dict)
        _fail(failures, f"{path} version", package.get("version"), bare_version)

    for path in sorted((ROOT / "packages").glob("*/*/pyproject.toml")):
        data = _read_toml(str(path.relative_to(ROOT)))
        project = data.get("project")
        if isinstance(project, dict):
            _fail(failures, f"{path.relative_to(ROOT)} project.version", project.get("version"), bare_version)

    tauri = _read_json("packages/apps/desktop/src-tauri/tauri.conf.json")
    assert isinstance(tauri, dict)
    _fail(failures, "desktop tauri.conf.json version", tauri.get("version"), bare_version)

    for path in CARGO_MANIFESTS:
        data = _read_toml(path)
        package = data.get("package")
        if isinstance(package, dict):
            _fail(failures, f"{path} package.version", package.get("version"), bare_version)

    tick_init = (ROOT / "packages/core/ticks/python/tick_engine/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', tick_init, re.MULTILINE)
    _fail(failures, "tick_engine __version__", match.group(1) if match else None, bare_version)

    if not (ROOT / release_note).exists():
        failures.append(f"missing current release note: {release_note}")

    site_generator = (ROOT / "packages/apps/site/scripts/generate-content.mjs").read_text(encoding="utf-8")
    if release_note not in site_generator:
        failures.append(f"site docs generator does not include {release_note}")
    if "const releasePages = releaseDocs.map" not in site_generator:
        failures.append("site docs generator must derive release sidebar pages from releaseDocs")

    for path in CURRENT_TAG_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        if version_tag not in text:
            failures.append(f"{path} does not mention current VERSION {version_tag}")
        stale_pattern = _stale_current_pattern(version_tag)
        stale = stale_pattern.search(text) if stale_pattern else None
        if stale:
            failures.append(f"{path} still mentions stale current beta tag {stale.group(0)!r}")

    for path in INSTALLER_POLICY_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        for phrase in STALE_INSTALLER_PHRASES:
            if phrase in text:
                failures.append(f"{path} still advertises unsupported beta installer artefact phrase {phrase!r}")

    # Retired subsystem names must not resurface as current-state claims in the
    # policy/docs surfaces (migration code, credits, and changelog history are
    # exempt by not being listed here).
    for path in RETIRED_NAME_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        for name in RETIRED_NAMES:
            if name in text:
                failures.append(f"{path} still names retired subsystem {name!r}")

    if failures:
        print("Version consistency check failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"Version consistency check passed for {version_tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
