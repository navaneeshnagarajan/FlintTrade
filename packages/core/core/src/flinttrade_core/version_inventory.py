"""Read-only, allowlisted runtime and dependency metadata for About.

Installed metadata is an observation, not an SDK attestation or a broker
qualification. Repository pins remain separate from installed versions. No
SDK is imported, and no source URL, filesystem path or host data is returned.
"""

from __future__ import annotations

import json
import platform
import re
import sqlite3
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any

from flinttrade_core.source_root import SourceRootError, discover_source_root
from flinttrade_core.version import APP_VERSION, UNKNOWN_VERSION

_PACKAGE_NAMES = (
    "flask",
    "werkzeug",
    "waitress",
    "pydantic",
    "httpx",
    "websockets",
    "numpy",
    "pandas",
    "duckdb",
    "pyarrow",
    "cryptography",
    "sentry-sdk",
    "flinttrade-ticks",
)
_BROKER_NAMES = ("dhanhq", "upstox-python-sdk", "kotakneoapi", "growwapi")
# Accept version labels, never arbitrary metadata text such as a URL or path.
_VERSION_PATTERN = re.compile(
    r"v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*"
    r"(?:[-_.]?(?:alpha|beta|preview|pre|rc|a|b|c)[-_.]?[0-9]*)?"
    r"(?:(?:-[0-9]+)|(?:[-_.]?(?:post|rev|r)[-_.]?[0-9]*))?"
    r"(?:[-_.]?dev[-_.]?[0-9]*)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?",
    re.IGNORECASE,
)
_COMMIT_PATTERN = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


def sanitise_version(value: object) -> str | None:
    """Return a bounded version label, excluding paths and arbitrary text."""
    if isinstance(value, str) and len(value) <= 128 and _VERSION_PATTERN.fullmatch(value):
        return value
    return None


def _safe_commit(value: object) -> str | None:
    if isinstance(value, str) and _COMMIT_PATTERN.fullmatch(value):
        return value.lower()
    return None


def _manifest_entries(root: Path | None, filename: str, table: str) -> dict[str, dict[str, Any]]:
    """Read named entries; missing, malformed or ambiguous entries are absent."""
    if root is None:
        return {}
    try:
        document = tomllib.loads((root / filename).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    entries = document.get(table)
    if not isinstance(entries, list):
        return {}
    by_name: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        name = re.sub(r"[-_.]+", "-", entry["name"]).lower()
        if name in by_name:
            ambiguous.add(name)
        by_name[name] = entry
    return {name: entry for name, entry in by_name.items() if name not in ambiguous}


def _installed_metadata(name: str, *, include_commit: bool = False) -> tuple[str | None, str | None]:
    """Read only the requested distribution's version and optional Git commit."""
    try:
        distribution = metadata.distribution(name)
        version = sanitise_version(distribution.version)
    except (metadata.PackageNotFoundError, OSError, ValueError, UnicodeError):
        return None, None
    if not include_commit:
        return version, None
    try:
        raw = distribution.read_text("direct_url.json")
        direct_url = json.loads(raw) if raw else None
    except (OSError, ValueError, UnicodeError):
        return version, None
    if not isinstance(direct_url, dict):
        return version, None
    vcs = direct_url.get("vcs_info")
    if not isinstance(vcs, dict) or vcs.get("vcs") != "git":
        return version, None
    return version, _safe_commit(vcs.get("commit_id"))


def build_version_inventory(*, source_root: Path | None = None) -> dict[str, Any]:
    """Return bounded About metadata without probing services or importing SDKs.

    Args:
        source_root: Repository manifest directory. By default, use validated
            source-checkout discovery. Missing checkout data is unavailable.

    Returns:
        App version, current Python/SQLite runtime versions, primary backend
        distribution versions and the four repository broker SDKs. ``None``
        means missing or unreadable metadata, never a configured fallback for
        an installed version. Configured package pins come from ``uv.lock``;
        broker versions and source commits come from ``brokers.lock``.
        A separate release version is included only when the broker pin has one.
    """
    if source_root is None:
        try:
            source_root = discover_source_root()
        except (SourceRootError, OSError):
            source_root = None
    package_pins = _manifest_entries(source_root, "uv.lock", "package")
    broker_pins = _manifest_entries(source_root, "brokers.lock", "broker")
    packages = []
    for name in _PACKAGE_NAMES:
        installed, _ = _installed_metadata(name)
        packages.append(
            {
                "name": name,
                "installed": installed,
                "configured": sanitise_version(package_pins.get(name, {}).get("version")),
            }
        )
    brokers = []
    for name in _BROKER_NAMES:
        installed, installed_commit = _installed_metadata(name, include_commit=True)
        pin = broker_pins.get(name, {})
        broker = {
            "name": name,
            "installed": installed,
            "configured": sanitise_version(pin.get("version")),
            "source_commit": _safe_commit(pin.get("source_commit")),
            "installed_commit": installed_commit,
        }
        if "release_version" in pin:
            broker["release_version"] = sanitise_version(pin["release_version"])
        brokers.append(broker)
    return {
        "app_version": sanitise_version(APP_VERSION) or UNKNOWN_VERSION,
        "runtimes": [
            {"name": "Python", "version": sanitise_version(platform.python_version())},
            {"name": "SQLite", "version": sanitise_version(sqlite3.sqlite_version)},
        ],
        "packages": packages,
        "brokers": brokers,
    }
