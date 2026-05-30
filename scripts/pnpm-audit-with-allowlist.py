#!/usr/bin/env python3
"""Run `pnpm audit --json`, drop allowlisted advisories, fail on HIGH/CRITICAL.

Mirrors scripts/pip-audit-with-allowlist.py for the node ecosystem. Allowlist entries
(supply-chain/pnpm-audit-allowlist.yml) expire on their `expires` field; expired entries
stop suppressing findings.

Handles both the pnpm v8/v9 audit JSON shapes:
  - {"advisories": {"<id>": {severity, module_name, ...}}, "metadata": {...}}
  - {"vulnerabilities": {...}}  (npm-style passthrough)

Sub-spec §5.3; acceptance gate #8.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST = REPO / "supply-chain" / "pnpm-audit-allowlist.yml"
BLOCKING_SEVERITIES = {"high", "critical"}


def _active_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    allow = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    today = dt.date.today()
    active: set[str] = set()
    for e in allow.get("allowlist") or []:
        advisory = e.get("advisory") or e.get("vuln_id")
        if not advisory:
            print(f"WARNING: allowlist entry without advisory id: {e}", file=sys.stderr)
            continue
        expires = e.get("expires")
        if expires and dt.date.fromisoformat(str(expires)) < today:
            print(f"NOTE: pnpm allowlist entry {advisory} expired on {expires}")
            continue
        active.add(str(advisory))
    return active


def _collect_advisories(report: dict) -> list[dict]:
    out: list[dict] = []
    for adv in (report.get("advisories") or {}).values():
        out.append({
            "id": str(adv.get("github_advisory_id") or adv.get("id") or "?"),
            "package": adv.get("module_name", "?"),
            "severity": (adv.get("severity") or "unknown").lower(),
            "url": adv.get("url", ""),
        })
    for pkg, v in (report.get("vulnerabilities") or {}).items():
        if not isinstance(v, dict):
            continue
        sev = (v.get("severity") or "unknown").lower()
        via = v.get("via") or []
        ids = [x.get("source") or x.get("url") for x in via if isinstance(x, dict)]
        out.append({
            "id": str(ids[0]) if ids else pkg,
            "package": v.get("name", pkg),
            "severity": sev,
            "url": "",
        })
    return out


def main() -> int:
    try:
        proc = subprocess.run(
            ["pnpm", "audit", "--json", "--audit-level", "high"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        print("pnpm not installed — run `corepack enable && pnpm install --frozen-lockfile` "
              "first (failing closed)", file=sys.stderr)
        return 2
    if not proc.stdout.strip():
        # pnpm exits 0 + empty when no advisories; non-empty stderr only on tooling error
        if proc.returncode not in (0, 1):
            print(f"pnpm audit tooling error (rc={proc.returncode}):\n{proc.stderr}",
                  file=sys.stderr)
            return 2
        print("pnpm audit: no advisories reported")
        return 0
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"pnpm audit emitted non-JSON: {e}\n{proc.stdout[:2000]}", file=sys.stderr)
        return 2

    (REPO / "pnpm-audit-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    active_allow = _active_allowlist()
    blocking: list[dict] = []
    for adv in _collect_advisories(report):
        if adv["severity"] not in BLOCKING_SEVERITIES:
            continue
        if adv["id"] in active_allow:
            print(f"ALLOWLISTED: {adv['id']} in {adv['package']}")
            continue
        blocking.append(adv)

    if blocking:
        print("BLOCKING:", json.dumps(blocking, indent=2))
        return 1
    print("pnpm audit clean (after allowlist filter)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
