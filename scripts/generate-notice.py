#!/usr/bin/env python3
"""Generate a lightweight notice inventory from committed lockfiles."""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    lines = ["FlintTrade third-party dependency notice", ""]
    for path in ["uv.lock", "requirements.lock", "pnpm-lock.yaml", "brokers.lock"]:
        lines.append(f"- {path}: {'present' if Path(path).exists() else 'missing'}")
    Path("notice.generated").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("notice.generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
