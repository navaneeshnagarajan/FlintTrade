#!/usr/bin/env python3
"""Run pip-audit with lock-bound provenance and an expiring allowlist.

Security M8 offline behaviour is deliberately fail-closed:
  - a trustworthy online report uses pip-audit's documented exit code 0 or 1;
  - an offline snapshot must be fresh, not future-dated, and bound to the exact
    current requirements.lock dependency set and SHA-256;
  - malformed, incomplete, skipped, or mismatched reports are rejected.

Use ``--snapshot-output PATH`` from the scheduled refresh workflow to capture a
validated, provenance-bearing online report without applying the allowlist.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

import yaml  # pinned in supply-chain/audit-tooling.lock
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

REPO = pathlib.Path(__file__).resolve().parents[1]
ALLOWLIST = REPO / "supply-chain" / "pip-audit-allowlist.yml"
LOCKFILE = REPO / "requirements.lock"
OUTPUT = pathlib.Path(os.environ.get("FLINTTRADE_PIP_AUDIT_REPORT", REPO / "pip-audit-report.json"))
SNAPSHOT_DIR = REPO / "supply-chain"
MAX_SNAPSHOT_AGE_DAYS = 14
REPORT_SCHEMA = "flinttrade-pip-audit-v1"
TRUSTWORTHY_PIP_AUDIT_EXIT_CODES = {0, 1}
KNOWN_SEVERITIES = {"LOW", "MEDIUM", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN"}
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL", "UNKNOWN"}
_LOCK_REQUIREMENT_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)",
)


class ReportValidationError(ValueError):
    """Raised when an audit report cannot prove coverage of the current lock."""


@dataclass(frozen=True)
class LockState:
    """Canonical dependency coverage and digest for requirements.lock."""

    path: pathlib.Path
    dependencies: dict[str, Version]
    sha256: str


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _format_timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("provenance timestamp must be timezone-aware")
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ReportValidationError(f"snapshot provenance {field} must be a timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ReportValidationError(f"snapshot provenance {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ReportValidationError(f"snapshot provenance {field} must include a timezone")
    return parsed.astimezone(dt.UTC)


def _load_lock_state(path: pathlib.Path = LOCKFILE) -> LockState:
    """Parse exact PEP 503 names and PEP 440 versions from a hashed uv export."""
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReportValidationError(f"cannot read {path}: {exc}") from exc

    dependencies: dict[str, Version] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line or line.startswith("#") or line[0].isspace():
            continue
        match = _LOCK_REQUIREMENT_RE.match(line)
        if match is None:
            raise ReportValidationError(f"unparsed requirement at {path}:{line_number}")
        name, raw_version = match.groups()
        remainder = line[match.end() :].strip()
        if remainder and not remainder.startswith((";", "\\")):
            raise ReportValidationError(f"unexpected requirement syntax at {path}:{line_number}")
        normalised_name = str(canonicalize_name(name))
        try:
            version = Version(raw_version)
        except InvalidVersion as exc:
            raise ReportValidationError(f"invalid version {raw_version!r} for {normalised_name} in {path}") from exc
        previous = dependencies.get(normalised_name)
        if previous is not None and previous != version:
            raise ReportValidationError(f"conflicting locked versions for {normalised_name}: {previous} and {version}")
        dependencies[normalised_name] = version

    if not dependencies:
        raise ReportValidationError(f"{path} contains no pinned dependencies")
    return LockState(path=path, dependencies=dependencies, sha256=hashlib.sha256(raw).hexdigest())


def _lock_is_unchanged(lock_state: LockState) -> bool:
    try:
        current = _load_lock_state(lock_state.path)
    except ReportValidationError as exc:
        print(f"cannot re-read requirements.lock: {exc}", file=sys.stderr)
        return False
    if current.sha256 != lock_state.sha256:
        print("requirements.lock changed while pip-audit was running (failing closed)", file=sys.stderr)
        return False
    return True


def _normalised_report_coverage(report: object) -> dict[str, Version]:
    if not isinstance(report, dict):
        raise ReportValidationError("pip-audit report must be a JSON object")
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise ReportValidationError("pip-audit report must contain a non-empty dependencies list")
    if not isinstance(report.get("fixes"), list):
        raise ReportValidationError("pip-audit report fixes must be a list")

    coverage: dict[str, Version] = {}
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            raise ReportValidationError(f"dependency {index} must be an object")
        name = dependency.get("name")
        raw_version = dependency.get("version")
        if not isinstance(name, str) or not name.strip():
            raise ReportValidationError(f"dependency {index} has no valid name")
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise ReportValidationError(f"dependency {name!r} has no valid version")
        if dependency.get("skip_reason"):
            raise ReportValidationError(f"dependency {name!r} was skipped by pip-audit")
        vulnerabilities = dependency.get("vulns")
        if not isinstance(vulnerabilities, list):
            raise ReportValidationError(f"dependency {name!r} has no valid vulns list")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ReportValidationError(f"dependency {name!r} has a malformed vulnerability")
            vulnerability_id = vulnerability.get("id")
            if not isinstance(vulnerability_id, str) or not vulnerability_id.strip():
                raise ReportValidationError(f"dependency {name!r} has a vulnerability without an id")

        normalised_name = str(canonicalize_name(name))
        try:
            version = Version(raw_version)
        except InvalidVersion as exc:
            raise ReportValidationError(f"dependency {normalised_name!r} has invalid version {raw_version!r}") from exc
        if normalised_name in coverage:
            raise ReportValidationError(f"duplicate dependency {normalised_name!r} in pip-audit report")
        coverage[normalised_name] = version
    return coverage


def _validate_report_coverage(report: object, lock_state: LockState) -> dict[str, Any]:
    coverage = _normalised_report_coverage(report)
    expected_names = set(lock_state.dependencies)
    actual_names = set(coverage)
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    mismatched = sorted(
        name for name in expected_names & actual_names if lock_state.dependencies[name] != coverage[name]
    )
    if missing or extra or mismatched:
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        if mismatched:
            versions = [f"{name}:{coverage[name]}!={lock_state.dependencies[name]}" for name in mismatched]
            details.append(f"version_mismatch={versions}")
        raise ReportValidationError(
            "pip-audit dependency coverage does not match requirements.lock: " + "; ".join(details)
        )
    assert isinstance(report, dict)
    return report


def _report_has_vulnerabilities(report: dict[str, Any]) -> bool:
    return any(dependency["vulns"] for dependency in report["dependencies"])


def _with_provenance(
    report: dict[str, Any],
    *,
    source: str,
    lock_state: LockState,
    generated_at: dt.datetime,
    audited_at: dt.datetime,
    pip_audit_exit_code: int,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """Add top-level provenance without changing pip-audit dependency data."""
    result = dict(report)
    provenance: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "source": source,
        "generated_at": _format_timestamp(generated_at),
        "audited_at": _format_timestamp(audited_at),
        "requirements_lock_sha256": lock_state.sha256,
        "pip_audit_exit_code": pip_audit_exit_code,
    }
    if snapshot is not None:
        provenance["snapshot"] = snapshot
    result["_meta"] = provenance
    return result


def _latest_snapshot() -> pathlib.Path | None:
    snapshots = sorted(SNAPSHOT_DIR.glob("vuln-snapshot-*.json"))
    return snapshots[-1] if snapshots else None


def _run_online_audit(
    lock_state: LockState,
    *,
    source: str = "online-osv",
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Return a validated online report for documented exit code 0 or 1 only."""
    try:
        proc = subprocess.run(
            [
                "pip-audit",
                "--require-hashes",
                "-r",
                str(lock_state.path),
                "--format",
                "json",
                "--vulnerability-service",
                "osv",
                "--disable-pip",
                "--strict",
                "--progress-spinner",
                "off",
                "--timeout",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except FileNotFoundError:
        print(
            "pip-audit not installed; run `pip install --require-hashes -r "
            "supply-chain/audit-tooling.lock` first (failing closed)",
            file=sys.stderr,
        )
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"pip-audit could not complete: {exc} (failing closed)", file=sys.stderr)
        return None

    if proc.returncode not in TRUSTWORTHY_PIP_AUDIT_EXIT_CODES:
        print(
            f"pip-audit failed operationally with status {proc.returncode}: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    if not proc.stdout.strip():
        print("pip-audit emitted empty output (failing closed)", file=sys.stderr)
        return None
    if not _lock_is_unchanged(lock_state):
        return None
    try:
        report = json.loads(proc.stdout)
        report = _validate_report_coverage(report, lock_state)
    except (json.JSONDecodeError, ReportValidationError) as exc:
        print(f"pip-audit emitted an untrustworthy report: {exc}", file=sys.stderr)
        return None

    has_vulnerabilities = _report_has_vulnerabilities(report)
    if (proc.returncode == 0 and has_vulnerabilities) or (proc.returncode == 1 and not has_vulnerabilities):
        print(
            "pip-audit exit status contradicts its vulnerability report (failing closed)",
            file=sys.stderr,
        )
        return None

    audited_at = now or _utc_now()
    return _with_provenance(
        report,
        source=source,
        lock_state=lock_state,
        generated_at=audited_at,
        audited_at=audited_at,
        pip_audit_exit_code=proc.returncode,
    )


def _validate_snapshot_provenance(
    report: dict[str, Any],
    snapshot: pathlib.Path,
    lock_state: LockState,
    now: dt.datetime,
) -> tuple[dt.datetime, int]:
    metadata = report.get("_meta")
    if not isinstance(metadata, dict):
        raise ReportValidationError("snapshot has no provenance metadata")
    if metadata.get("schema") != REPORT_SCHEMA:
        raise ReportValidationError("snapshot provenance schema is unsupported")
    if metadata.get("source") != "online-osv-snapshot":
        raise ReportValidationError("snapshot provenance source is not an online OSV capture")
    if metadata.get("requirements_lock_sha256") != lock_state.sha256:
        raise ReportValidationError("snapshot requirements.lock digest does not match the current lock")

    return_code = metadata.get("pip_audit_exit_code")
    if isinstance(return_code, bool) or return_code not in TRUSTWORTHY_PIP_AUDIT_EXIT_CODES:
        raise ReportValidationError("snapshot has an untrustworthy pip-audit exit code")

    generated_at = _parse_timestamp(metadata.get("generated_at"), "generated_at")
    audited_at = _parse_timestamp(metadata.get("audited_at"), "audited_at")
    if generated_at < audited_at:
        raise ReportValidationError("snapshot generation time predates its audit time")
    if generated_at > now or audited_at > now:
        raise ReportValidationError("snapshot provenance is future-dated")
    if now - audited_at > dt.timedelta(days=MAX_SNAPSHOT_AGE_DAYS):
        raise ReportValidationError(f"snapshot is older than {MAX_SNAPSHOT_AGE_DAYS} days")

    prefix = "vuln-snapshot-"
    date_text = snapshot.stem[len(prefix) :] if snapshot.stem.startswith(prefix) else ""
    try:
        filename_date = dt.date.fromisoformat(date_text)
    except ValueError as exc:
        raise ReportValidationError("snapshot filename has an invalid date") from exc
    if filename_date > now.date():
        raise ReportValidationError("snapshot filename is future-dated")
    if filename_date != audited_at.date():
        raise ReportValidationError("snapshot filename date does not match its audit provenance")

    has_vulnerabilities = _report_has_vulnerabilities(report)
    if (return_code == 0 and has_vulnerabilities) or (return_code == 1 and not has_vulnerabilities):
        raise ReportValidationError("snapshot exit status contradicts its vulnerability report")
    return audited_at, return_code


def _load_offline_snapshot(
    lock_state: LockState,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any] | None:
    """Load a fresh snapshot bound to the exact current requirements.lock."""
    snapshot = _latest_snapshot()
    if snapshot is None:
        print("OSV unavailable and no local snapshot exists (failing closed)", file=sys.stderr)
        return None
    current_time = now or _utc_now()
    try:
        report = json.loads(snapshot.read_text(encoding="utf-8"))
        report = _validate_report_coverage(report, lock_state)
        audited_at, return_code = _validate_snapshot_provenance(
            report,
            snapshot,
            lock_state,
            current_time,
        )
    except (OSError, json.JSONDecodeError, ReportValidationError) as exc:
        print(f"cached snapshot {snapshot.name} is untrustworthy: {exc}", file=sys.stderr)
        return None

    print(f"OSV unavailable; evaluating validated cached snapshot {snapshot.name}")
    return _with_provenance(
        report,
        source="cached-osv-snapshot",
        lock_state=lock_state,
        generated_at=current_time,
        audited_at=audited_at,
        pip_audit_exit_code=return_code,
        snapshot=snapshot.name,
    )


def _active_allowlist() -> set[tuple[str, str]]:
    if not ALLOWLIST.exists():
        return set()
    allow = yaml.safe_load(ALLOWLIST.read_text(encoding="utf-8")) or {}
    today = dt.date.today()
    active: set[tuple[str, str]] = set()
    for entry in allow.get("allowlist") or []:
        missing = [key for key in ("vuln_id", "package", "reason", "accepted_by", "expires") if key not in entry]
        if missing:
            print(f"WARNING: allowlist entry missing required keys {missing}: {entry}", file=sys.stderr)
            continue
        if dt.date.fromisoformat(str(entry["expires"])) >= today:
            active.add((entry["vuln_id"], str(canonicalize_name(entry["package"]))))
        else:
            print(
                f"NOTE: allowlist entry for {entry['vuln_id']} expired on {entry['expires']}; "
                "it no longer suppresses findings"
            )
    return active


def _normalise_severity(value: object) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    normalised = value.strip().upper()
    return normalised if normalised in KNOWN_SEVERITIES else "UNKNOWN"


def _blocking_findings(
    report: dict[str, Any],
    active_allow: set[tuple[str, str]],
) -> list[dict[str, str]]:
    """Return non-allowlisted HIGH, CRITICAL, or unknown-severity findings."""
    blocking: list[dict[str, str]] = []
    for dependency in report.get("dependencies", []):
        for vulnerability in dependency.get("vulns", []):
            severity = _normalise_severity(vulnerability.get("severity"))
            if severity not in BLOCKING_SEVERITIES:
                continue
            key = (vulnerability["id"], str(canonicalize_name(dependency["name"])))
            if key in active_allow:
                print(f"ALLOWLISTED: {vulnerability['id']} in {dependency['name']} {dependency['version']}")
                continue
            blocking.append(
                {
                    "id": vulnerability["id"],
                    "package": dependency["name"],
                    "version": dependency["version"],
                    "severity": severity,
                }
            )
    return blocking


def _remove_stale_output(path: pathlib.Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"cannot remove stale audit output {path}: {exc}", file=sys.stderr)
        return False
    return True


def _write_json(path: pathlib.Path, report: dict[str, Any]) -> None:
    """Atomically publish a validated report without leaving a partial artefact."""
    temporary: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = pathlib.Path(handle.name)
            json.dump(report, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_current_lock() -> LockState | None:
    try:
        return _load_lock_state()
    except ReportValidationError as exc:
        print(f"cannot establish requirements.lock coverage: {exc}", file=sys.stderr)
        return None


def _capture_snapshot(path: pathlib.Path) -> int:
    if not _remove_stale_output(path):
        return 2
    lock_state = _load_current_lock()
    if lock_state is None:
        return 2
    report = _run_online_audit(lock_state, source="online-osv-snapshot")
    if report is None:
        return 2
    if not _lock_is_unchanged(lock_state):
        return 2
    try:
        _write_json(path, report)
    except OSError as exc:
        print(f"cannot publish validated snapshot {path}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote validated OSV snapshot {path}")
    return 0


def _run_gate() -> int:
    if not _remove_stale_output(OUTPUT):
        return 2
    lock_state = _load_current_lock()
    if lock_state is None:
        return 2

    report = _run_online_audit(lock_state)
    if report is None:
        report = _load_offline_snapshot(lock_state)
    if report is None:
        return 2
    if not _lock_is_unchanged(lock_state):
        return 2

    try:
        _write_json(OUTPUT, report)
    except OSError as exc:
        print(f"cannot publish validated audit report {OUTPUT}: {exc}", file=sys.stderr)
        return 2

    blocking = _blocking_findings(report, _active_allowlist())
    if blocking:
        print("BLOCKING:", json.dumps(blocking, indent=2))
        return 1
    print("pip-audit clean (after allowlist filter)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-output",
        type=pathlib.Path,
        help="capture a validated online OSV report for the offline snapshot workflow",
    )
    args = parser.parse_args(argv)
    if args.snapshot_output is not None:
        return _capture_snapshot(args.snapshot_output)
    return _run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
