#!/usr/bin/env python3
"""Sync repo-local broker SDK reference mirrors.

The runtime installation is still controlled by ``uv.lock`` and
``packages/integrations/gateway/pyproject.toml``. This script gives agents and
maintainers a repeatable way to keep the corresponding SDK source/artifact
references inside the checkout at ``.local/sdk-audit/`` for parity checks,
without committing vendored SDK code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = REPO / "brokers.lock"
DEFAULT_AUDIT_ROOT = REPO / ".local" / "sdk-audit"


@dataclass(frozen=True)
class BrokerSdkSource:
    """Known upstream locations for an installable broker SDK pin."""

    package: str
    repo_name: str | None = None
    git_url: str | None = None
    pypi_name: str | None = None
    notes: str = ""


SDK_SOURCES: dict[str, BrokerSdkSource] = {
    "dhanhq": BrokerSdkSource(
        package="dhanhq",
        repo_name="dhanhq-py",
        git_url="https://github.com/dhan-oss/dhanhq-py.git",
        pypi_name="dhanhq",
    ),
    "upstox-python-sdk": BrokerSdkSource(
        package="upstox-python-sdk",
        repo_name="upstox-python",
        git_url="https://github.com/upstox/upstox-python.git",
        pypi_name="upstox-python-sdk",
    ),
    "neo-api-client": BrokerSdkSource(
        package="neo-api-client",
        repo_name="kotak-neo-api-v2",
        git_url="https://github.com/Kotak-Neo/Kotak-neo-api-v2.git",
        notes="Kotak Neo publishes this SDK from GitHub; package metadata remains version 2.0.0.",
    ),
    "growwapi": BrokerSdkSource(
        package="growwapi",
        pypi_name="growwapi",
        notes="Groww's official Python SDK is currently distributed through PyPI docs/package metadata.",
    ),
}

SDKLESS_BROKERS: tuple[dict[str, str], ...] = (
    {
        "broker": "indmoney",
        "advertised_package": "indstocks-sdk",
        "pypi_json": "https://pypi.org/pypi/indstocks-sdk/json",
        "npm_json": "https://registry.npmjs.org/indstocks-sdk",
        "reason": "INDstocks advertises SDK install commands, but no package exists on PyPI or npm yet.",
    },
)


UrlOpener = Callable[[str], tuple[int, bytes]]


def _open_url(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "flinttrade-sdk-sync/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            return int(status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _display_path(path: Path) -> str:
    """Return a repo-relative path when possible, otherwise an absolute path."""

    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO))
    except ValueError:
        return str(resolved)


def load_broker_lock(path: Path = DEFAULT_LOCK) -> list[dict[str, Any]]:
    """Return broker entries from ``brokers.lock``."""

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    brokers = data.get("broker", [])
    return [entry for entry in brokers if isinstance(entry, dict)]


def active_sdk_entries(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return non-placeholder SDK entries that have known upstream locations."""

    out: list[dict[str, str]] = []
    for entry in entries:
        name = str(entry.get("name", "")).strip()
        version = str(entry.get("version", "")).strip()
        if not name or not version or "PLACEHOLDER" in version.upper():
            continue
        if name not in SDK_SOURCES:
            continue
        source_commit = str(entry.get("source_commit", "")).strip()
        row = {
            "name": name,
            "version": version,
            "source_commit": source_commit,
        }
        sha256 = str(entry.get("sha256", "")).strip()
        if sha256:
            # Carried so the downloaded audit artifact can be cross-checked
            # against the brokers.lock pin (not only PyPI's self-advertised
            # digest) — PyPI may add files to an existing release.
            row["sha256"] = sha256
        out.append(row)
    return out


def sync_git_mirror(source: BrokerSdkSource, audit_root: Path) -> dict[str, str]:
    """Clone or fetch an SDK source repository under ``audit_root``."""

    if not source.git_url or not source.repo_name:
        return {}
    repo = audit_root / source.repo_name
    if repo.exists():
        if not (repo / ".git").exists():
            raise RuntimeError(f"{repo} exists but is not a git checkout")
        _run(["git", "-C", str(repo), "fetch", "--tags", "--prune", "origin"])
    else:
        repo.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", source.git_url, str(repo)])
    # Drift must be measured against the REMOTE head, not the local checkout's
    # HEAD: `git fetch` only updates remote-tracking refs, so rev-parse HEAD is
    # frozen at clone time and would report `git-current` forever even after
    # upstream moves — silently defeating the drift gate for the one SDK whose
    # only distribution channel is git (Renovate cannot watch git-pinned uv
    # sources either).
    remote_head = _run(["git", "-C", str(repo), "ls-remote", "origin", "HEAD"]).split()[0]
    return {
        "path": str(repo.relative_to(REPO)),
        "remote": _run(["git", "-C", str(repo), "remote", "get-url", "origin"]),
        "head": remote_head,
        "describe": _run(["git", "-C", str(repo), "describe", "--tags", "--always", "--dirty"]),
    }


def pypi_release_json(package: str, opener: UrlOpener = _open_url) -> dict[str, Any]:
    """Fetch PyPI metadata for ``package``."""

    status, body = opener(f"https://pypi.org/pypi/{package}/json")
    if status != 200:
        raise RuntimeError(f"PyPI returned HTTP {status} for {package}")
    return json.loads(body.decode("utf-8"))


def latest_pypi_version(package: str, opener: UrlOpener = _open_url) -> str:
    """Return the latest version advertised by PyPI for ``package``."""

    data = pypi_release_json(package, opener)
    version = str((data.get("info") or {}).get("version") or "").strip()
    if not version:
        raise RuntimeError(f"PyPI metadata for {package} did not include info.version")
    return version


def select_pypi_artifact(files: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Pick the best audit artifact from a PyPI release file list."""

    if not files:
        raise RuntimeError("PyPI release has no files")

    def score(file: Mapping[str, Any]) -> tuple[int, str]:
        packagetype = str(file.get("packagetype", ""))
        filename = str(file.get("filename", ""))
        python_version = str(file.get("python_version", ""))
        if packagetype == "bdist_wheel" and python_version == "py3" and filename.endswith("none-any.whl"):
            return (0, filename)
        if packagetype == "bdist_wheel":
            return (1, filename)
        if packagetype == "sdist":
            return (2, filename)
        return (3, filename)

    return min(files, key=score)


def download_pypi_artifact(
    package: str,
    version: str,
    out_dir: Path,
    opener: UrlOpener = _open_url,
    pinned_sha: str = "",
) -> dict[str, str]:
    """Download the pinned PyPI artifact and verify its SHA256 digest.

    The download is verified against BOTH PyPI's self-advertised digest AND the
    ``pinned_sha`` recorded in brokers.lock (when supplied). PyPI permits adding
    files to an existing release, and this tool prefers wheels over sdists, so a
    match against PyPI's own digest alone could silently cache an artifact
    different from the one the repo pinned. A mismatch against the brokers.lock
    pin is a supply-chain red flag and raises.
    """

    data = pypi_release_json(package, opener)
    releases = data.get("releases", {})
    files = releases.get(version)
    if not isinstance(files, list):
        raise RuntimeError(f"PyPI has no release files for {package}=={version}")
    artifact = select_pypi_artifact(files)
    url = str(artifact["url"])
    filename = str(artifact["filename"])
    expected_sha = str((artifact.get("digests") or {}).get("sha256") or "")
    status, body = opener(url)
    if status != 200:
        raise RuntimeError(f"artifact download returned HTTP {status} for {filename}")
    actual_sha = hashlib.sha256(body).hexdigest()
    if expected_sha and actual_sha != expected_sha:
        raise RuntimeError(f"sha256 mismatch for {filename}: expected {expected_sha}, got {actual_sha}")
    pin = pinned_sha.strip().lower()
    matched_brokers_lock = None
    if pin and "placeholder" not in pin:
        # brokers.lock records the artifact sha256 for PyPI brokers (the same
        # value requirements.lock pins). A mismatch means PyPI is serving a
        # different artifact for this pinned release than the repo attested.
        if actual_sha != pin:
            raise RuntimeError(
                f"brokers.lock sha256 mismatch for {package}=={version} ({filename}): "
                f"pinned {pin}, downloaded {actual_sha}"
            )
        matched_brokers_lock = True
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / filename
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(target)
    result = {
        "path": _display_path(target),
        "filename": filename,
        "sha256": actual_sha,
        "url": url,
    }
    if matched_brokers_lock is not None:
        result["brokers_lock_sha_match"] = "true"
    return result


def registry_status(url: str, opener: UrlOpener = _open_url) -> str:
    """Return a compact HTTP status string for a package-registry URL."""

    status, _body = opener(url)
    return str(status)


def build_readme(manifest: dict[str, Any]) -> str:
    """Render a short human-readable summary for ``.local/sdk-audit``."""

    lines = [
        "# Broker SDK Audit Cache",
        "",
        "Generated by `uv run python scripts/sync_broker_sdk_refs.py`.",
        "This directory is gitignored and contains repo-local SDK source mirrors and package artifacts.",
        "",
        f"Generated at: {manifest['generated_at']}",
        "",
        "## SDKs",
        "",
    ]
    for entry in manifest["sdks"]:
        lines.append(f"- {entry['package']} {entry['version']}")
        if entry.get("git"):
            lines.append(f"  - git: {entry['git']['path']} @ {entry['git']['describe']}")
            if "git_current" in entry:
                status = "current" if entry["git_current"] else "locked behind upstream HEAD"
                lines.append(f"  - git status: {status}")
        if entry.get("pypi"):
            lines.append(f"  - pypi: {entry['pypi']['path']}")
            latest = entry.get("pypi_latest_version")
            if latest:
                status = "current" if entry.get("pypi_current") else "locked behind latest"
                lines.append(f"  - PyPI latest: {latest} ({status})")
        if entry.get("notes"):
            lines.append(f"  - notes: {entry['notes']}")
    if manifest.get("drift"):
        lines.extend(["", "## Drift", ""])
        for entry in manifest["drift"]:
            lines.append(f"- {entry['package']}: locked {entry['locked']} vs upstream {entry['upstream']} ({entry['source']})")
    if manifest.get("sdkless_brokers"):
        lines.extend(["", "## SDK-Less Brokers", ""])
        for entry in manifest["sdkless_brokers"]:
            lines.append(
                f"- {entry['broker']}: {entry['advertised_package']} "
                f"(PyPI {entry.get('pypi_status', 'unchecked')}, npm {entry.get('npm_status', 'unchecked')})"
            )
            lines.append(f"  - reason: {entry['reason']}")
    lines.append("")
    return "\n".join(lines)


def sync(
    *,
    lock_path: Path = DEFAULT_LOCK,
    audit_root: Path = DEFAULT_AUDIT_ROOT,
    check_missing: bool = True,
    opener: UrlOpener = _open_url,
) -> dict[str, Any]:
    """Sync all known broker SDK references and return the manifest."""

    audit_root.mkdir(parents=True, exist_ok=True)
    pypi_dir = audit_root / "pypi"
    entries = active_sdk_entries(load_broker_lock(lock_path))
    manifest: dict[str, Any] = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "lock_path": _display_path(lock_path),
        "audit_root": _display_path(audit_root),
        "sdks": [],
        "drift": [],
        "sdkless_brokers": [],
    }
    for entry in entries:
        source = SDK_SOURCES[entry["name"]]
        sdk_record: dict[str, Any] = {
            "package": entry["name"],
            "version": entry["version"],
            "source_commit": entry["source_commit"],
            "notes": source.notes,
        }
        if source.git_url:
            git = sync_git_mirror(source, audit_root)
            sdk_record["git"] = git
            if entry["source_commit"]:
                current = str(git.get("head", "")) == entry["source_commit"]
                sdk_record["git_current"] = current
                if not current:
                    manifest["drift"].append(
                        {
                            "package": entry["name"],
                            "source": "git",
                            "locked": entry["source_commit"],
                            "upstream": str(git.get("head", "")),
                        }
                    )
        if source.pypi_name:
            latest = latest_pypi_version(source.pypi_name, opener)
            sdk_record["pypi_latest_version"] = latest
            sdk_record["pypi_current"] = latest == entry["version"]
            if latest != entry["version"]:
                manifest["drift"].append(
                    {
                        "package": entry["name"],
                        "source": "pypi",
                        "locked": entry["version"],
                        "upstream": latest,
                    }
                )
            sdk_record["pypi"] = download_pypi_artifact(
                source.pypi_name,
                entry["version"],
                pypi_dir,
                opener,
                pinned_sha=entry.get("sha256", ""),
            )
        manifest["sdks"].append(sdk_record)

    for sdkless in SDKLESS_BROKERS:
        record = dict(sdkless)
        if check_missing:
            record["pypi_status"] = registry_status(record["pypi_json"], opener)
            record["npm_status"] = registry_status(record["npm_json"], opener)
        else:
            record["pypi_status"] = "unchecked"
            record["npm_status"] = "unchecked"
        manifest["sdkless_brokers"].append(record)

    (audit_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (audit_root / "README.md").write_text(build_readme(manifest), encoding="utf-8")
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="brokers.lock path")
    parser.add_argument("--audit-root", type=Path, default=DEFAULT_AUDIT_ROOT, help="output directory")
    parser.add_argument(
        "--skip-missing-registry-check",
        action="store_true",
        help="do not query PyPI/npm for SDK-less broker evidence",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help="return a non-zero status if any locked SDK is behind upstream metadata",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest = sync(
        lock_path=args.lock,
        audit_root=args.audit_root,
        check_missing=not args.skip_missing_registry_check,
    )
    print(f"synced {len(manifest['sdks'])} broker SDK refs into {manifest['audit_root']}")
    for entry in manifest["sdks"]:
        bits = [f"{entry['package']}=={entry['version']}"]
        if entry.get("git"):
            bits.append(f"git={entry['git']['describe']}")
            if "git_current" in entry:
                bits.append("git-current" if entry["git_current"] else "git-drift")
        if entry.get("pypi"):
            bits.append(f"artifact={entry['pypi']['filename']}")
            bits.append("pypi-current" if entry.get("pypi_current") else "pypi-drift")
        print(" - " + ", ".join(bits))
    if manifest.get("drift"):
        print("drift detected:")
        for entry in manifest["drift"]:
            print(f" - {entry['package']}: locked {entry['locked']} vs upstream {entry['upstream']} ({entry['source']})")
    return 1 if args.fail_on_drift and manifest.get("drift") else 0


if __name__ == "__main__":
    raise SystemExit(main())
