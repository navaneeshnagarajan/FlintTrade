#!/usr/bin/env python3
"""Check that required files were touched by a restructure commit."""

from __future__ import annotations

import argparse
import subprocess
import sys

REQUIRED_BY_COMMIT: dict[str, set[str]] = {
    "0": {
        "flinttrade-design/baselines/packages-2026-05-23.csv",
        "flinttrade-design/baselines/blueprints-2026-05-23.csv",
        "flinttrade-design/baselines/operator-data-2026-05-23.csv",
        "flinttrade-design/baselines/MANIFEST.json",
        "packages/core/core/src/workspace_migrations.py",
        "packages/core/core/tests/test_workspace_migrations.py",
        "scripts/dump-blueprints.py",
    },
    "1": {
        ".github/workflows/site.yml",
        ".github/workflows/test.yml",
        "Dockerfile",
        "LICENSE",
        "flint.toml",
        "VERSION",
        "pyproject.toml",
        "Makefile",
        "docker-compose.yml",
        "changelog.md",
        "code-of-conduct.md",
        "contributing.md",
        "licenses/agpl-3.0.txt",
        "licenses/apache-2.0.txt",
        "licenses/cc-by-4.0.txt",
        "licenses/plug-in-exception.txt",
        "notice",
        "readme.md",
        "security.md",
    },
}


def _changed(base_ref: str) -> set[str]:
    committed = subprocess.check_output(["git", "diff", "--name-only", f"{base_ref}..HEAD"], text=True)
    worktree = subprocess.check_output(["git", "diff", "--name-only", base_ref], text=True)
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], text=True)
    lines = committed.splitlines() + worktree.splitlines() + untracked.splitlines()
    return {line.strip() for line in lines if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", choices=sorted(REQUIRED_BY_COMMIT), required=True)
    parser.add_argument("--base-ref", default="HEAD~1")
    args = parser.parse_args()

    changed = _changed(args.base_ref)
    missing = sorted(REQUIRED_BY_COMMIT[args.commit] - changed)
    if missing:
        print("required files not touched:")
        for path in missing:
            print(f"  {path}")
        return 1
    print(f"commit {args.commit} doc-sync touched {len(REQUIRED_BY_COMMIT[args.commit])} required files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
