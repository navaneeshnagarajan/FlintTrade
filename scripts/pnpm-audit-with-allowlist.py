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
    if not isinstance(report, dict) or "error" in report or not any(
        key in report for key in ("advisories", "vulnerabilities")
    ):
        raise ValueError("Missing audit result")
    for key in ("advisories", "vulnerabilities"):
        if key not in report:
            continue
        records = report[key]
        if not isinstance(records, dict):
            raise ValueError("Invalid advisory collection")
        for value in records.values():
            if not isinstance(value, dict) or value.get("severity") not in {
                "info", "low", "moderate", "high", "critical"
            }:
                raise ValueError("Invalid advisory severity")
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
    output = REPO / "pnpm-audit-report.json"
    try:
        output.unlink(missing_ok=True)
    except OSError:
        print("Cannot retire stale audit evidence (failing closed)", file=sys.stderr)
        return 2
    try:
        proc = subprocess.run(
            ["pnpm", "audit", "--json", "--audit-level", "high"],
            capture_output=True, text=True, check=False,
            cwd=REPO, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("pnpm audit unavailable (failing closed)", file=sys.stderr)
        return 2
    if proc.returncode not in (0, 1) or not proc.stdout.strip():
        print("pnpm audit did not produce valid evidence (failing closed)", file=sys.stderr)
        return 2
    try:
        report = json.loads(proc.stdout)
        advisories = _collect_advisories(report)
        expected_failure = any(adv["severity"] in BLOCKING_SEVERITIES for adv in advisories)
        if (proc.returncode == 1) != expected_failure:
            raise ValueError("Audit exit status contradicts the result")
        active_allow = _active_allowlist()
    except (ValueError, TypeError, AttributeError, OSError, yaml.YAMLError):
        print("pnpm audit evidence or allowlist invalid (failing closed)", file=sys.stderr)
        return 2

    try:
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        print("Cannot persist audit evidence (failing closed)", file=sys.stderr)
        return 2
    blocking: list[dict] = []
    for adv in advisories:
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
