#!/usr/bin/env python3
"""Verify every broker SDK in brokers.lock declares a licence in the AGPL allowlist.

Reads brokers.lock; for each entry, asserts the declared SPDX licence is in
supply-chain/licence-allowlist.yml. When the wheel is installed in the current
environment, cross-checks the wheel metadata licence against the declared value.

Fails on:
  - brokers.lock declares a licence in the denylist
  - brokers.lock declares a licence not in the allowlist
  - installed wheel metadata declares a licence not in the allowlist that also
    disagrees with brokers.lock

PLACEHOLDER entries (future-wave brokers not yet activated) are skipped — they are
gated separately by scripts/check-brokers-lock.py and runtime SDK attestation.

Sub-spec §7.4; acceptance gate #10.
"""

from __future__ import annotations

import importlib.metadata as md
import pathlib
import sys
import tomllib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
BROKERS_LOCK = REPO / "brokers.lock"
ALLOWLIST_FILE = REPO / "supply-chain" / "licence-allowlist.yml"

# Wheel `License` metadata is overwhelmingly free-text, not an SPDX identifier
# (e.g. dhanhq ships "MIT License"). Normalise the common forms to their SPDX id so
# the cross-check compares like with like instead of failing on cosmetic differences.
_FREE_TEXT_TO_SPDX = {
    "mit": "MIT",
    "mit license": "MIT",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "apache 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "the apache software license, version 2.0": "Apache-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "isc": "ISC",
    "isc license (iscl)": "ISC",
    "python software foundation license": "Python-2.0",
    "gnu general public license v3 or later (gplv3+)": "GPL-3.0-or-later",
    "gnu affero general public license v3 or later (agpl3+)": "AGPL-3.0-or-later",
}


def _normalise_spdx(raw: str) -> str:
    s = (raw or "").strip()
    return _FREE_TEXT_TO_SPDX.get(s.lower(), s)


def _extract_metadata_licence(name: str) -> str | None:
    """Return the SPDX 'License-Expression' or normalised 'License' field, or None."""
    try:
        meta = md.metadata(name)
    except md.PackageNotFoundError:
        return None
    raw = (meta.get("License-Expression") or meta.get("License") or "").strip()
    return _normalise_spdx(raw) or None


def _is_distribution_installed(name: str) -> bool:
    try:
        md.version(name)
    except md.PackageNotFoundError:
        return False
    return True


def _is_placeholder_entry(entry: dict[str, object]) -> bool:
    """True when an inactive broker wave has not populated its full SDK pin."""
    fields = (
        str(entry.get("version", "")),
        str(entry.get("sha256", "")),
        str(entry.get("licence", "")),
    )
    return any("PLACEHOLDER" in field.upper() for field in fields)


def main() -> int:
    if not BROKERS_LOCK.exists():
        print(f"brokers.lock missing at {BROKERS_LOCK}", file=sys.stderr)
        return 1
    if not ALLOWLIST_FILE.exists():
        print(f"licence allowlist missing at {ALLOWLIST_FILE}", file=sys.stderr)
        return 1

    allow = yaml.safe_load(ALLOWLIST_FILE.read_text(encoding="utf-8")) or {}
    allowed = set(allow.get("allowlist") or [])
    deny = set(allow.get("denylist") or [])
    review = set(allow.get("classification_review") or [])

    data = tomllib.loads(BROKERS_LOCK.read_text(encoding="utf-8"))
    fails: list[str] = []
    checked = 0
    for entry in data.get("broker", []):
        name = entry["name"]
        declared = (entry.get("licence", "") or "").strip()
        if _is_placeholder_entry(entry) or not declared:
            # future-wave broker not yet activated; check-brokers-lock.py gates these
            continue
        checked += 1
        if declared in deny:
            fails.append(f"{name}: brokers.lock declares FORBIDDEN licence {declared!r}")
            continue
        if declared not in allowed:
            if declared in review:
                print(f"REVIEW: {name} declares {declared!r} (needs founder classification)")
                continue
            fails.append(
                f"{name}: brokers.lock declares {declared!r} which is not in the allowlist; "
                f"add it to supply-chain/licence-allowlist.yml with founder approval, "
                f"or use a different SDK"
            )
            continue
        installed = _extract_metadata_licence(name)
        if installed is None:
            if _is_distribution_installed(name):
                print(f"NOTE: {name} installed but has no wheel licence metadata; relying on brokers.lock")
            else:
                print(f"NOTE: {name} not installed here; skipping wheel-metadata cross-check")
            continue
        if installed != declared and installed not in allowed:
            fails.append(
                f"{name}: installed wheel declares {installed!r} but brokers.lock has "
                f"{declared!r}; the installed value is not in the allowlist either"
            )

    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1
    print(f"broker SDK licences OK ({checked} active entries checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
