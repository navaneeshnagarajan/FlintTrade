#!/usr/bin/env python3
"""Generate a notice inventory from the committed lockfiles (sub-spec §8).

Each tracked lockfile contributes its presence + a sha256 of its contents, so any
dependency change (which necessarily changes a lockfile) surfaces as drift in
``notice.generated`` until the founder regenerates it.

Usage:
  python scripts/generate-notice.py            # write notice.generated in place
  python scripts/generate-notice.py --check     # exit 1 if notice.generated is stale/missing
  python scripts/generate-notice.py --diff      # print the unified diff (no write)
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "notice.generated"
LOCKFILES = ("uv.lock", "requirements.lock", "pnpm-lock.yaml", "brokers.lock",
             "supply-chain/audit-tooling.lock")


def _render() -> str:
    lines = [
        "FlintTrade third-party dependency notice",
        "",
        "flinttrade is licensed under AGPL-3.0-or-later. The dependencies tracked by the",
        "lockfiles below carry their own licences; see the NOTICE/notices bundle and",
        "supply-chain/licence-allowlist.yml for the compatibility policy.",
        "",
    ]
    for rel in LOCKFILES:
        p = REPO / rel
        if p.exists():
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"- {rel}: present (sha256: {digest})")
        else:
            lines.append(f"- {rel}: missing")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if notice.generated is stale or missing")
    parser.add_argument("--diff", action="store_true",
                        help="print the unified diff vs the committed notice.generated")
    args = parser.parse_args()

    rendered = _render()
    committed = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""

    if args.diff:
        sys.stdout.writelines(difflib.unified_diff(
            committed.splitlines(keepends=True), rendered.splitlines(keepends=True),
            fromfile="notice.generated (committed)", tofile="notice.generated (regenerated)",
        ))
        return 0

    if args.check:
        if committed == rendered:
            print("notice.generated up to date")
            return 0
        print("NOTICE drift: notice.generated is stale. Run "
              "`python scripts/generate-notice.py` and commit the result.", file=sys.stderr)
        sys.stdout.writelines(difflib.unified_diff(
            committed.splitlines(keepends=True), rendered.splitlines(keepends=True),
            fromfile="committed", tofile="regenerated",
        ))
        return 1

    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
