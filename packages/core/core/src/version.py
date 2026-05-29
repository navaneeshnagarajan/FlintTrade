"""Central FlintTrade product version helpers.

The repository root ``VERSION`` file is the source of truth for the app-wide
release label. Python package metadata stores the same value without the
leading ``v`` because package managers expect bare SemVer-like versions.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path

UNKNOWN_VERSION = "0.0.0-dev"


def _normalise_version(value: str) -> str:
    return value.strip().removeprefix("v")


def _tag_version(value: str) -> str:
    normalised = _normalise_version(value)
    return normalised if normalised.startswith("v") else f"v{normalised}"


def _find_repo_version_file(start: Path | None = None) -> Path | None:
    current = (start or Path(__file__)).resolve()
    for parent in [current.parent, *current.parents]:
        candidate = parent / "VERSION"
        if candidate.exists():
            return candidate
    return None


def read_app_version() -> str:
    """Return the FlintTrade app version without a leading ``v``."""
    version_file = _find_repo_version_file()
    if version_file is not None:
        return _normalise_version(version_file.read_text(encoding="utf-8"))

    try:
        return _normalise_version(package_version("flinttrade-core"))
    except PackageNotFoundError:
        return UNKNOWN_VERSION


APP_VERSION = read_app_version()
APP_VERSION_TAG = _tag_version(APP_VERSION)


__all__ = ["APP_VERSION", "APP_VERSION_TAG", "UNKNOWN_VERSION", "read_app_version"]
