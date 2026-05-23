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
        "packages/core/src/workspace_migrations.py",
        "packages/core/tests/test_workspace_migrations.py",
        "scripts/dump-blueprints.py",
    },
    "1": {
        "flint.toml",
        "VERSION",
        "pyproject.toml",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        ".github/workflows/test.yml",
        ".github/workflows/site.yml",
    },
}


def _changed(base_ref: str) -> set[str]:
    output = subprocess.check_output(["git", "diff", "--name-only", f"{base_ref}..HEAD"], text=True)
    return {line.strip() for line in output.splitlines() if line.strip()}


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
