#!/usr/bin/env python3
"""Capture per-file line-count and hash baselines for restructure reality checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

DEFAULT_OUTPUT = Path("flinttrade-design/baselines/per-file-line-counts-2026-05-23.csv")
SOURCE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".rs",
    ".toml",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    ".yml",
    ".yaml",
    ".css",
    ".md",
}
SKIP_PARTS = {
    ".git",
    ".local",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "target",
}


def _include(path: Path) -> bool:
    return path.is_file() and path.suffix in SOURCE_EXTENSIONS and not (set(path.parts) & SKIP_PARTS)


def _line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = []
    for root in (Path("packages"), Path("apps"), Path("infra"), Path("scripts"), Path("tests")):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not _include(path):
                continue
            data = path.read_bytes()
            rows.append(
                {
                    "path": path.as_posix(),
                    "line_count": _line_count(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "modified_at": int(path.stat().st_mtime),
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "line_count", "sha256", "modified_at"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
