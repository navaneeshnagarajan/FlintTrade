#!/usr/bin/env python3
"""Assert every transitive dependency licence is in the AGPL allowlist.

Parallels scripts/check-broker-sdk-licences.py but covers the full transitive set
(non-broker deps too). Reads supply-chain/transitive-licences.json — produced in CI by
`python -m pip_licenses --from=mixed --order=license --format=json --output-file=...` —
and checks every dep against supply-chain/licence-allowlist.yml.

Unlike the broker-SDK gate this job is INFORMATIONAL (continue-on-error in CI): a single
transitive dep relicensing typically needs a phased response (file upstream issue, swap
the dep) rather than an immediate hard block. The script still returns 1 on disallowed
licences so the signal is visible; the workflow decides whether it blocks.

Sub-spec §7.5.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST_FILE = REPO / "supply-chain" / "licence-allowlist.yml"
REPORT = REPO / "supply-chain" / "transitive-licences.json"

# Common non-SPDX free-text licence strings pip_licenses emits, mapped to SPDX.
_NORMALISE = {
    "MIT License": "MIT",
    "MIT license": "MIT",
    "BSD License": "BSD-3-Clause",
    "BSD": "BSD-3-Clause",
    "Apache Software License": "Apache-2.0",
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "The Apache Software License, Version 2.0": "Apache-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "Python-2.0",
}


def _split_licences(raw: str) -> list[str]:
    """pip_licenses may emit 'MIT; BSD' or 'Apache-2.0 OR MIT'."""
    parts = re.split(r"\s*(?:;|\bOR\b|\bor\b|/)\s*", (raw or "").strip())
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    if not REPORT.exists():
        print(f"NOTE: {REPORT.name} not generated yet; skipping transitive sweep")
        return 0
    allow = yaml.safe_load(ALLOWLIST_FILE.read_text(encoding="utf-8")) or {}
    allowed = set(allow.get("allowlist") or [])
    deny = set(allow.get("denylist") or [])
    review = set(allow.get("classification_review") or [])

    data = json.loads(REPORT.read_text(encoding="utf-8"))
    fails: list[str] = []
    reviews: list[str] = []
    for entry in data:
        name = entry.get("Name", "?")
        version = entry.get("Version", "?")
        raw = entry.get("License", "")
        candidates = _split_licences(raw) or [""]
        normalised = [_NORMALISE.get(c, c) for c in candidates]
        # a dep is OK if ANY of its declared licences is allowed (dual-licensed deps)
        if any(c in allowed for c in normalised):
            continue
        if any(c in deny for c in normalised):
            fails.append(f"{name} {version}: FORBIDDEN licence {raw!r}")
            continue
        if any((c in review or c == "") for c in normalised):
            reviews.append(f"{name} {version}: {raw!r} (needs classification)")
            continue
        fails.append(f"{name} {version}: licence {raw!r} not in allowlist")

    for r in reviews:
        print(f"REVIEW: {r}")
    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"transitive licences OK ({len(data)} deps checked, {len(reviews)} need review)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
