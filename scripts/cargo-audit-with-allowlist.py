#!/usr/bin/env python3
"""Run cargo-audit and fail on unreviewed advisories.

Vulnerabilities are never suppressed. The PyO3 tick engine currently has no
accepted RustSec warnings; any future warning must be explicitly reviewed and
time-bounded in supply-chain/cargo-audit-allowlist.yml.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
from typing import Any

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST = REPO / "supply-chain" / "cargo-audit-allowlist.yml"


def _active_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    raw = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    today = dt.date.today()
    active: set[str] = set()
    for entry in raw.get("allowlist") or []:
        advisory = str(entry.get("advisory") or "")
        if not advisory:
            print(f"WARNING: cargo audit allowlist entry missing advisory id: {entry}", file=sys.stderr)
            continue
        expires = entry.get("expires")
        if expires and dt.date.fromisoformat(str(expires)) < today:
            print(f"NOTE: cargo audit allowlist entry {advisory} expired on {expires}", file=sys.stderr)
            continue
        active.add(advisory)
    return active


def _warning_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    warnings = report.get("warnings") or {}
    if not isinstance(warnings, dict):
        return items
    for kind, entries in warnings.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                items.append({**entry, "kind": kind})
    return items


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-dir", required=True, help="directory containing Cargo.lock")
    parser.add_argument("--report", required=True, help="JSON report output path, relative to repo root")
    args = parser.parse_args()

    manifest_dir = (REPO / args.manifest_dir).resolve()
    report_path = (REPO / args.report).resolve()
    proc = subprocess.run(
        ["cargo", "+stable", "audit", "--json"],
        cwd=manifest_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if not proc.stdout.strip():
        print(proc.stderr, file=sys.stderr)
        return proc.returncode or 2

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"cargo audit emitted non-JSON: {exc}\n{proc.stdout[:2000]}", file=sys.stderr)
        return 2

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    vulnerabilities = (report.get("vulnerabilities") or {}).get("list") or []
    if vulnerabilities:
        blocking = [
            {
                "id": item.get("advisory", {}).get("id"),
                "package": item.get("advisory", {}).get("package"),
                "title": item.get("advisory", {}).get("title"),
            }
            for item in vulnerabilities
        ]
        print("BLOCKING cargo vulnerabilities:", json.dumps(blocking, indent=2), file=sys.stderr)
        return 1

    active_allowlist = _active_allowlist()
    unreviewed: list[dict[str, str | None]] = []
    for item in _warning_items(report):
        advisory = item.get("advisory") or {}
        advisory_id = str(advisory.get("id") or "")
        if advisory_id in active_allowlist:
            print(f"ALLOWLISTED: {advisory_id} in {advisory.get('package')}")
            continue
        unreviewed.append({
            "id": advisory_id,
            "package": advisory.get("package"),
            "kind": item.get("kind"),
            "title": advisory.get("title"),
        })

    if unreviewed:
        print("UNREVIEWED cargo warnings:", json.dumps(unreviewed, indent=2), file=sys.stderr)
        return 1

    print(f"cargo audit clean for {args.manifest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
