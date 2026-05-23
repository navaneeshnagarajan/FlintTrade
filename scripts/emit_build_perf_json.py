#!/usr/bin/env python3
"""Emit build performance baseline JSON from captured build logs."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import gzip
import json
import os
import platform
from pathlib import Path


def _wall_seconds(log_path: Path) -> float:
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("wall_seconds="):
            return float(line.split("=", 1)[1])
    return 0.0


def _dir_size_mb(path: Path) -> int:
    if not path.exists():
        return 0
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return round(total / (1024 * 1024))


def _ts_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for p in path.rglob("*") if p.suffix in {".ts", ".tsx"} and "node_modules" not in p.parts)


def _bundle_kb_gzipped(paths: list[Path]) -> int:
    total = 0
    for root in paths:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".js", ".css"} or not path.is_file():
                continue
            total += len(gzip.compress(path.read_bytes()))
    return round(total / 1024)


def _entry(name: str, source: Path, outputs: list[Path], log: Path) -> dict[str, float | int]:
    return {
        "wall_seconds": _wall_seconds(log),
        "bundle_kb_gzipped": _bundle_kb_gzipped(outputs),
        "ts_files": _ts_files(source),
        "node_modules_mb": _dir_size_mb(source / "node_modules"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terminal-log", type=Path, required=True)
    parser.add_argument("--site-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = {
        "terminal": _entry(
            "terminal",
            Path("packages/terminal"),
            [Path("packages/terminal/dist/assets")],
            args.terminal_log,
        ),
        "site": _entry(
            "site",
            Path("apps/site"),
            [Path("apps/site/.next/static")],
            args.site_log,
        ),
        "captured_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "captured_by": "scripts/capture-build-perf-baseline.sh",
        "host": {
            "cpu_model": platform.processor() or platform.machine(),
            "ram_gb": round((os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024**3))
            if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names
            else 0,
            "platform": platform.platform(),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
