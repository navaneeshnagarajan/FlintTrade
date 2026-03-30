#!/usr/bin/env python3
"""Check upstream version drift for all tracked dependencies.

Compares local submodule commits and absorbed repo snapshots against
their upstream remotes. Outputs a markdown table showing what's behind.

Usage:
    python scripts/check_upstream.py
    python scripts/check_upstream.py --format json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class RepoStatus:
    name: str
    category: str  # "submodule" | "reference" | "npm" | "pip"
    local_version: str = ""
    remote_version: str = ""
    commits_behind: int = 0
    url: str = ""
    notes: str = ""


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    """Run a command and return stdout, empty string on failure."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def check_submodules() -> list[RepoStatus]:
    """Check git submodules for upstream drift."""
    results: list[RepoStatus] = []

    submodules = [
        ("infra/openalgo", "marketcalls/openalgo", "main"),
        ("infra/algomirror", "marketcalls/algomirror", "main"),
        ("infra/openclaw", "openclaw/openclaw", "main"),
    ]

    for path, repo, branch in submodules:
        sub_path = ROOT / path
        if not sub_path.exists():
            results.append(RepoStatus(
                name=path, category="submodule",
                notes="Directory not found",
                url=f"https://github.com/{repo}",
            ))
            continue

        # Get local commit
        local = _run(["git", "rev-parse", "--short", "HEAD"], cwd=sub_path)

        # Fetch upstream
        _run(["git", "fetch", "origin", "--quiet"], cwd=sub_path)

        # Get remote commit
        remote = _run(
            ["git", "rev-parse", "--short", f"origin/{branch}"],
            cwd=sub_path,
        )

        # Count commits behind
        behind_str = _run(
            ["git", "rev-list", f"HEAD..origin/{branch}", "--count"],
            cwd=sub_path,
        )
        behind = int(behind_str) if behind_str.isdigit() else 0

        # Get latest tag on remote
        latest_tag = _run(
            ["git", "describe", "--tags", "--abbrev=0", f"origin/{branch}"],
            cwd=sub_path,
        )

        results.append(RepoStatus(
            name=path,
            category="submodule",
            local_version=local,
            remote_version=f"{remote} ({latest_tag})" if latest_tag else remote,
            commits_behind=behind,
            url=f"https://github.com/{repo}",
            notes="UP TO DATE" if behind == 0 else f"{behind} commits behind",
        ))

    return results


def check_npm_deps() -> list[RepoStatus]:
    """Check key npm dependencies for version drift."""
    results: list[RepoStatus] = []

    pkg_json_path = ROOT / "packages" / "terminal" / "package.json"
    if not pkg_json_path.exists():
        return results

    with open(pkg_json_path) as f:
        pkg = json.load(f)

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

    # Key deps to track
    key_deps = [
        "react", "dockview-react", "lightweight-charts",
        "@glideapps/glide-data-grid", "@tanstack/react-query",
        "zustand", "jotai", "tailwindcss", "vite", "react-resizable-panels",
    ]

    for dep_name in key_deps:
        local_ver = deps.get(dep_name, "not installed")
        # Strip ^ or ~ prefix
        local_clean = local_ver.lstrip("^~")

        # Check latest from npm registry
        latest = _run(["npm", "view", dep_name, "version"])

        behind = 0
        if latest and local_clean and latest != local_clean:
            behind = 1  # simplified — just flag as "update available"

        results.append(RepoStatus(
            name=dep_name,
            category="npm",
            local_version=local_clean,
            remote_version=latest or "unknown",
            commits_behind=behind,
            url=f"https://www.npmjs.com/package/{dep_name}",
            notes="UP TO DATE" if behind == 0 else f"Update available: {latest}",
        ))

    return results


def check_pip_deps() -> list[RepoStatus]:
    """Check key pip dependencies for version drift."""
    results: list[RepoStatus] = []

    key_deps = [
        "flask", "httpx", "pydantic", "duckdb", "chromadb",
        "lightgbm", "ruff", "pytest",
    ]

    for dep_name in key_deps:
        # Get installed version
        local = _run([sys.executable, "-m", "pip", "show", dep_name])
        local_ver = ""
        for line in local.splitlines():
            if line.startswith("Version:"):
                local_ver = line.split(":", 1)[1].strip()
                break

        # Get latest from PyPI
        latest = _run(
            [sys.executable, "-m", "pip", "index", "versions", dep_name]
        )
        latest_ver = ""
        if latest:
            # Format: "dep_name (X.Y.Z)"
            parts = latest.split("(")
            if len(parts) > 1:
                latest_ver = parts[1].split(")")[0].strip()

        behind = 0
        if latest_ver and local_ver and latest_ver != local_ver:
            behind = 1

        results.append(RepoStatus(
            name=dep_name,
            category="pip",
            local_version=local_ver or "not installed",
            remote_version=latest_ver or "unknown",
            commits_behind=behind,
            notes="UP TO DATE" if behind == 0 else f"Update available: {latest_ver}",
        ))

    return results


def format_markdown(results: list[RepoStatus]) -> str:
    """Format results as markdown table."""
    lines = [
        "# FlintTrade — Upstream Version Drift Report",
        "",
        f"> Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Group by category
    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    for cat, items in categories.items():
        behind_count = sum(1 for i in items if i.commits_behind > 0)
        lines.append(f"## {cat.upper()} ({behind_count}/{len(items)} need updates)")
        lines.append("")
        lines.append("| Name | Local | Latest | Status |")
        lines.append("|------|-------|--------|--------|")

        for item in sorted(items, key=lambda x: -x.commits_behind):
            status = item.notes
            if item.commits_behind > 0:
                status = f"**{status}**"
            lines.append(f"| {item.name} | {item.local_version} | {item.remote_version} | {status} |")

        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check upstream version drift")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--skip-pip", action="store_true", help="Skip pip checks (slow)")
    parser.add_argument("--skip-npm", action="store_true", help="Skip npm checks (slow)")
    args = parser.parse_args()

    results: list[RepoStatus] = []

    print("Checking submodules...", file=sys.stderr)
    results.extend(check_submodules())

    if not args.skip_npm:
        print("Checking npm dependencies...", file=sys.stderr)
        results.extend(check_npm_deps())

    if not args.skip_pip:
        print("Checking pip dependencies...", file=sys.stderr)
        results.extend(check_pip_deps())

    if args.format == "json":
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(format_markdown(results))


if __name__ == "__main__":
    main()
