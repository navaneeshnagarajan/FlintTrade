#!/usr/bin/env python3
"""Validate FlintTrade visual-regression capture directories."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

TERMINAL_ROUTES = [
    "root",
    "welcome",
    "explore",
    "setup",
    "setup-account",
    "home",
    "trade",
    "terminal",
    "invest",
    "learn",
    "lab",
    "automate",
    "ai",
    "ditto",
    "settings",
    "admin",
    "login",
    "missing-route-for-404",
]
SITE_ROUTES = [
    "root",
    "docs",
    "api-reference",
    "mcp",
    "contribute",
    "api-mcp",
    "api-search",
    "missing-route-for-404",
]
VIEWPORTS = {
    "1920x1080": (1920, 1080),
    "1366x768": (1366, 768),
    "768x1024": (768, 1024),
}
THEMES = ["dark", "light"]
DENSITIES = ["compact", "comfortable"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def expected_paths(root: Path) -> dict[Path, tuple[int, int]]:
    expected: dict[Path, tuple[int, int]] = {}
    for app, routes in {"terminal": TERMINAL_ROUTES, "site": SITE_ROUTES}.items():
        for route in routes:
            for viewport, dimensions in VIEWPORTS.items():
                for theme in THEMES:
                    for density in DENSITIES:
                        expected[root / app / route / viewport / theme / f"{density}.png"] = dimensions
    return expected


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        signature = handle.read(8)
        if signature != PNG_SIGNATURE:
            raise ValueError("not a PNG")
        length = struct.unpack(">I", handle.read(4))[0]
        chunk_type = handle.read(4)
        if chunk_type != b"IHDR" or length < 8:
            raise ValueError("missing IHDR")
        data = handle.read(length)
    return struct.unpack(">II", data[:8])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--min-bytes", type=int, default=0)
    args = parser.parse_args()

    root = args.capture_dir
    expected = expected_paths(root)
    actual = set(root.rglob("*.png")) if root.exists() else set()
    expected_set = set(expected)

    missing = sorted(path.relative_to(root).as_posix() for path in expected_set - actual)
    extra = sorted(path.relative_to(root).as_posix() for path in actual - expected_set)
    too_small: list[str] = []
    wrong_dimensions: list[str] = []

    for path, dimensions in sorted(expected.items()):
        if not path.exists():
            continue
        if args.min_bytes and path.stat().st_size < args.min_bytes:
            too_small.append(path.relative_to(root).as_posix())
        try:
            actual_dimensions = png_dimensions(path)
        except ValueError as exc:
            wrong_dimensions.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        if actual_dimensions != dimensions:
            wrong_dimensions.append(
                f"{path.relative_to(root).as_posix()}: expected {dimensions[0]}x{dimensions[1]}, "
                f"got {actual_dimensions[0]}x{actual_dimensions[1]}"
            )

    print(f"expected={len(expected)} actual={len(actual)}")
    if missing:
        print(f"missing={len(missing)}")
        for path in missing[:20]:
            print(f"  {path}")
    if extra:
        print(f"extra={len(extra)}")
        for path in extra[:20]:
            print(f"  {path}")
    if too_small:
        print(f"too_small={len(too_small)}")
        for path in too_small[:20]:
            print(f"  {path}")
    if wrong_dimensions:
        print(f"wrong_dimensions={len(wrong_dimensions)}")
        for path in wrong_dimensions[:20]:
            print(f"  {path}")

    if missing or extra or too_small or wrong_dimensions:
        return 1
    print("visual capture OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
