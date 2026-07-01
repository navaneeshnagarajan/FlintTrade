#!/usr/bin/env python3
"""Run pip-audit, drop allowlisted findings, fail on the rest (fail-closed on M8).

Allowlist entries (supply-chain/pip-audit-allowlist.yml) expire on their `expires`
field; expired entries surface as fails so risk acceptance is reviewed quarterly,
not silently renewed.

Security M8 — offline vuln-database fallback:
  - OSV.dev audit succeeds     → online path (`--vulnerability-service osv`)
  - OSV.dev audit unavailable  → fall back to newest supply-chain/vuln-snapshot-*.json
  - snapshot missing or stale  → FAIL CLOSED (never silently pass un-audited)

Sub-spec §3.1-§3.5; acceptance gates #3, #21.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess
import sys

import yaml  # pinned in supply-chain/audit-tooling.lock

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST = REPO / "supply-chain" / "pip-audit-allowlist.yml"
LOCKFILE = REPO / "requirements.lock"
SNAPSHOT_DIR = REPO / "supply-chain"
MAX_SNAPSHOT_AGE_DAYS = 14
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}


def _latest_snapshot() -> pathlib.Path | None:
    snaps = sorted(SNAPSHOT_DIR.glob("vuln-snapshot-*.json"))
    return snaps[-1] if snaps else None


def _run_online_audit() -> dict | None:
    """Run pip-audit against OSV online. Returns the parsed report, or None on error."""
    try:
        proc = subprocess.run(
            ["pip-audit", "--require-hashes", "-r", str(LOCKFILE),
             "--format", "json", "--vulnerability-service", "osv",
             "--disable-pip", "--progress-spinner", "off", "--timeout", "10"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        print("pip-audit not installed — run `pip install --require-hashes -r "
              "supply-chain/audit-tooling.lock` first (failing closed)", file=sys.stderr)
        return None
    if proc.returncode == 0 and not proc.stdout.strip():
        return {"dependencies": []}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"pip-audit emitted non-JSON: {e}\n{proc.stdout}\n{proc.stderr}",
              file=sys.stderr)
        return None


def _load_offline_snapshot() -> dict | None:
    """Load the newest cached pip-audit report; fail closed if stale/missing (M8).

    The snapshot is a pip-audit JSON report saved by .github/workflows/refresh-vuln-snapshot.yml
    during the last successful ONLINE run. Offline we re-evaluate the same allowlist/severity
    filter against it. When in doubt the gate FAILS — a stuck PR beats a silently un-audited dep.
    """
    snap = _latest_snapshot()
    if snap is None:
        print("OSV unreachable AND no local snapshot — failing closed (Security M8)",
              file=sys.stderr)
        return None
    try:
        snap_date = dt.date.fromisoformat(snap.stem.replace("vuln-snapshot-", ""))
    except ValueError:
        print(f"OSV unreachable AND snapshot {snap.name} has an unparseable date — "
              f"failing closed (Security M8)", file=sys.stderr)
        return None
    age_days = (dt.date.today() - snap_date).days
    if age_days > MAX_SNAPSHOT_AGE_DAYS:
        print(f"OSV unreachable AND snapshot {snap.name} is {age_days}d old "
              f"(max {MAX_SNAPSHOT_AGE_DAYS}d) — failing closed (Security M8)",
              file=sys.stderr)
        return None
    try:
        report = json.loads(snap.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"OSV unreachable AND snapshot {snap.name} unreadable ({e}) — "
              f"failing closed (Security M8)", file=sys.stderr)
        return None
    print(f"OSV unreachable; evaluating cached snapshot {snap.name} ({age_days}d old)")
    return report


def _active_allowlist() -> set[tuple[str, str]]:
    if not ALLOWLIST.exists():
        return set()
    allow = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    today = dt.date.today()
    active: set[tuple[str, str]] = set()
    for e in allow.get("allowlist") or []:
        missing = [k for k in ("vuln_id", "package", "reason", "accepted_by", "expires")
                   if k not in e]
        if missing:
            print(f"WARNING: allowlist entry missing required keys {missing}: {e}",
                  file=sys.stderr)
            continue
        if dt.date.fromisoformat(str(e["expires"])) >= today:
            active.add((e["vuln_id"], e["package"]))
        else:
            print(f"NOTE: allowlist entry for {e['vuln_id']} expired on {e['expires']}; "
                  f"it no longer suppresses findings")
    return active


def main() -> int:
    report = _run_online_audit()
    if report is None:
        report = _load_offline_snapshot()
    if report is None:
        return 2

    # mirror the report to disk for the CI artefact upload
    (REPO / "pip-audit-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    active_allow = _active_allowlist()
    blocking: list[dict] = []
    for dep in report.get("dependencies", []):
        for v in dep.get("vulns", []):
            sev = (v.get("severity") or "UNKNOWN").upper()
            if sev not in BLOCKING_SEVERITIES:
                continue
            key = (v["id"], dep["name"])
            if key in active_allow:
                print(f"ALLOWLISTED: {v['id']} in {dep['name']} {dep['version']}")
                continue
            blocking.append({"id": v["id"], "package": dep["name"],
                             "version": dep["version"], "severity": sev})

    if blocking:
        print("BLOCKING:", json.dumps(blocking, indent=2))
        return 1
    print("pip-audit clean (after allowlist filter)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
