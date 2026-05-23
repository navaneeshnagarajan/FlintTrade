#!/usr/bin/env python3
"""Fail if uv.lock / requirements.lock are absent from the supply-chain baseline."""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    missing = [str(path) for path in (Path("uv.lock"), Path("requirements.lock")) if not path.exists()]
    if missing:
        print("missing lockfile(s): " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
