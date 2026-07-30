"""Deterministic regression tests for the fail-closed pip-audit wrapper."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.version import Version

FIXED_NOW = dt.datetime(2026, 7, 13, 6, 30, tzinfo=dt.UTC)


def _load_module():
    path = Path(__file__).resolve().parents[1] / "pip-audit-with-allowlist.py"
    spec = importlib.util.spec_from_file_location("pip_audit_with_allowlist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _lock_state(module, tmp_path: Path, *dependencies: tuple[str, str]):
    lock = tmp_path / "requirements.lock"
    body = "".join(f"{name}=={version}\n" for name, version in dependencies)
    lock.write_text(body, encoding="utf-8")
    return module._load_lock_state(lock)


def _dependency(
    name: str = "example-package",
    version: str = "1.0.0",
    vulnerabilities: list[dict] | None = None,
) -> dict:
    return {
        "name": name,
        "version": version,
        "vulns": [] if vulnerabilities is None else vulnerabilities,
    }


def _report(*dependencies: dict) -> dict:
    return {
        "dependencies": list(dependencies) or [_dependency()],
        "fixes": [],
    }


def _vulnerability(severity: object = None) -> dict:
    vulnerability = {"id": "CVE-2099-0001"}
    if severity is not None:
        vulnerability["severity"] = severity
    return vulnerability


def _snapshot_report(module, lock_state, report: dict, audited_at: dt.datetime, return_code: int = 0) -> dict:
    return module._with_provenance(
        report,
        source="online-osv-snapshot",
        lock_state=lock_state,
        generated_at=audited_at,
        audited_at=audited_at,
        pip_audit_exit_code=return_code,
    )


def _mock_pip_audit(monkeypatch, module, *, returncode: int, stdout: str, stderr: str = "") -> None:
    result = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: result)


def test_lock_state_normalises_names_versions_and_binds_raw_digest(tmp_path: Path) -> None:
    module = _load_module()
    lock = tmp_path / "requirements.lock"
    raw = (b"Example_Package==1.0.0\npycparser==3.0 ; implementation_name != 'PyPy'\n")
    lock.write_bytes(raw)

    state = module._load_lock_state(lock)

    assert state.dependencies == {
        "example-package": Version("1.0.0"),
        "pycparser": Version("3.0"),
    }
    assert state.sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    ("dependencies", "message"),
    [
        ([_dependency("alpha", "1")], "missing=['beta']"),
        ([_dependency("alpha", "1"), _dependency("beta", "2"), _dependency("gamma", "3")], "extra=['gamma']"),
        ([_dependency("alpha", "1"), _dependency("beta", "9")], "version_mismatch=['beta:9!=2']"),
    ],
)
def test_report_coverage_rejects_missing_extra_and_mismatched_dependencies(
    tmp_path: Path,
    dependencies: list[dict],
    message: str,
) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("alpha", "1"), ("beta", "2"))

    with pytest.raises(module.ReportValidationError, match=re.escape(message)):
        module._validate_report_coverage(_report(*dependencies), state)


def test_report_coverage_accepts_pep_503_names_and_equivalent_pep_440_versions(tmp_path: Path) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("Example_Package", "1.0"))

    validated = module._validate_report_coverage(
        _report(_dependency("example-package", "1.0.0")),
        state,
    )

    assert validated["dependencies"][0]["name"] == "example-package"


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"dependencies": []},
        {"dependencies": "not-a-list"},
        {"dependencies": [_dependency()]},
        {"dependencies": [{"name": "example-package", "version": "1.0.0"}]},
        {"dependencies": [_dependency(), _dependency("Example_Package")]},
        {"dependencies": [{**_dependency(), "skip_reason": "not on index"}]},
        {"dependencies": [_dependency(vulnerabilities=[{}])]},
        {"dependencies": [_dependency()], "fixes": {}},
    ],
)
def test_report_schema_rejects_empty_malformed_duplicate_or_skipped_data(tmp_path: Path, report: object) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))

    with pytest.raises(module.ReportValidationError):
        module._validate_report_coverage(report, state)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "UNKNOWN"),
        ("", "UNKNOWN"),
        (" severe ", "UNKNOWN"),
        ("CVSS:3.1/AV:N/AC:L", "UNKNOWN"),
        ({"type": "CVSS_V3", "score": "9.8"}, "UNKNOWN"),
        (9.8, "UNKNOWN"),
        (" high ", "HIGH"),
        ("critical", "CRITICAL"),
        ("moderate", "MODERATE"),
        (" medium ", "MEDIUM"),
        ("low", "LOW"),
    ],
)
def test_severity_is_stripped_normalised_and_unknown_shapes_fail_closed(raw: object, expected: str) -> None:
    module = _load_module()

    assert module._normalise_severity(raw) == expected


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "MODERATE"])
def test_known_non_blocking_severities_remain_non_blocking(severity: str) -> None:
    module = _load_module()
    report = _report(_dependency(vulnerabilities=[_vulnerability(severity)]))

    assert module._blocking_findings(report, set()) == []


@pytest.mark.parametrize("severity", [None, "UNKNOWN", "unexpected", {"score": "9.8"}])
def test_unknown_severity_blocks_unless_allowlisted(severity: object) -> None:
    module = _load_module()
    report = _report(_dependency("Example_Package", vulnerabilities=[_vulnerability(severity)]))

    assert module._blocking_findings(report, set())[0]["severity"] == "UNKNOWN"
    assert module._blocking_findings(report, {("CVE-2099-0001", "example-package")}) == []


def test_online_audit_accepts_documented_clean_exit_and_emits_provenance(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    raw_report = _report(_dependency())
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout=json.dumps(raw_report), stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    report = module._run_online_audit(state, now=FIXED_NOW)

    assert report is not None
    assert "--strict" in captured["command"]
    assert report["dependencies"] == raw_report["dependencies"]
    assert report["fixes"] == raw_report["fixes"]
    assert report["_meta"] == {
        "schema": module.REPORT_SCHEMA,
        "source": "online-osv",
        "generated_at": "2026-07-13T06:30:00Z",
        "audited_at": "2026-07-13T06:30:00Z",
        "requirements_lock_sha256": state.sha256,
        "pip_audit_exit_code": 0,
    }


def test_online_audit_accepts_documented_vulnerability_exit(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    raw_report = _report(_dependency(vulnerabilities=[_vulnerability()]))
    _mock_pip_audit(monkeypatch, module, returncode=1, stdout=json.dumps(raw_report))

    report = module._run_online_audit(state, now=FIXED_NOW)

    assert report is not None
    assert report["_meta"]["pip_audit_exit_code"] == 1


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (2, json.dumps(_report(_dependency()))),
        (0, ""),
        (0, "not-json"),
        (0, "{}"),
        (0, json.dumps(_report(_dependency("different-package")))),
        (0, json.dumps(_report(_dependency(vulnerabilities=[_vulnerability()])))),
        (1, json.dumps(_report(_dependency()))),
    ],
)
def test_online_audit_rejects_operational_empty_malformed_mismatched_or_contradictory_results(
    tmp_path: Path,
    monkeypatch,
    returncode: int,
    stdout: str,
) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    _mock_pip_audit(monkeypatch, module, returncode=returncode, stdout=stdout, stderr="failure")

    assert module._run_online_audit(state, now=FIXED_NOW) is None


def test_online_audit_rejects_missing_executable(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))

    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", missing)

    assert module._run_online_audit(state, now=FIXED_NOW) is None


def test_online_audit_rejects_lock_mutation_during_execution(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    raw_report = _report(_dependency())

    def mutate_lock(*args, **kwargs):
        state.path.write_text("example-package==2.0.0\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps(raw_report), stderr="")

    monkeypatch.setattr(module.subprocess, "run", mutate_lock)

    assert module._run_online_audit(state, now=FIXED_NOW) is None


def test_cached_snapshot_requires_matching_lock_and_emits_runtime_provenance(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    audited_at = FIXED_NOW - dt.timedelta(days=1)
    snapshot = tmp_path / f"vuln-snapshot-{audited_at.date().isoformat()}.json"
    snapshot.write_text(
        json.dumps(_snapshot_report(module, state, _report(_dependency()), audited_at)),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "SNAPSHOT_DIR", tmp_path)

    report = module._load_offline_snapshot(state, now=FIXED_NOW)

    assert report is not None
    assert report["dependencies"] == [_dependency()]
    assert report["_meta"] == {
        "schema": module.REPORT_SCHEMA,
        "source": "cached-osv-snapshot",
        "generated_at": "2026-07-13T06:30:00Z",
        "audited_at": "2026-07-12T06:30:00Z",
        "requirements_lock_sha256": state.sha256,
        "pip_audit_exit_code": 0,
        "snapshot": snapshot.name,
    }


@pytest.mark.parametrize(
    "case",
    [
        "stale",
        "future-time",
        "future-filename",
        "filename-mismatch",
        "wrong-lock",
        "wrong-coverage",
        "missing-provenance",
        "untrusted-return-code",
        "contradictory-return-code",
    ],
)
def test_cached_snapshot_rejects_untrustworthy_provenance_or_coverage(
    tmp_path: Path,
    monkeypatch,
    case: str,
) -> None:
    module = _load_module()
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    audited_at = FIXED_NOW - dt.timedelta(days=1)
    raw_report = _report(_dependency())
    return_code = 0
    if case == "stale":
        audited_at = FIXED_NOW - dt.timedelta(days=15)
    elif case == "future-time":
        audited_at = FIXED_NOW + dt.timedelta(minutes=1)
    elif case == "wrong-coverage":
        raw_report = _report(_dependency("different-package"))
    elif case == "contradictory-return-code":
        return_code = 1

    report = _snapshot_report(module, state, raw_report, audited_at, return_code)
    filename_date = audited_at.date()
    if case == "future-filename":
        filename_date = (FIXED_NOW + dt.timedelta(days=1)).date()
    elif case == "filename-mismatch":
        filename_date = (audited_at - dt.timedelta(days=1)).date()
    elif case == "wrong-lock":
        report["_meta"]["requirements_lock_sha256"] = "f" * 64
    elif case == "missing-provenance":
        report.pop("_meta")
    elif case == "untrusted-return-code":
        report["_meta"]["pip_audit_exit_code"] = 2

    snapshot = tmp_path / f"vuln-snapshot-{filename_date.isoformat()}.json"
    snapshot.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(module, "SNAPSHOT_DIR", tmp_path)

    assert module._load_offline_snapshot(state, now=FIXED_NOW) is None


def test_gate_removes_stale_output_before_failed_audit(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "pip-audit-report.json"
    output.write_text('{"stale": true}', encoding="utf-8")
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    monkeypatch.setattr(module, "OUTPUT", output)
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state: None)
    monkeypatch.setattr(module, "_load_offline_snapshot", lambda lock_state: None)

    assert module._run_gate() == 2
    assert not output.exists()


def test_gate_writes_only_valid_provenance_bearing_report(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "pip-audit-report.json"
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    report = module._with_provenance(
        _report(_dependency()),
        source="online-osv",
        lock_state=state,
        generated_at=FIXED_NOW,
        audited_at=FIXED_NOW,
        pip_audit_exit_code=0,
    )
    monkeypatch.setattr(module, "OUTPUT", output)
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state: report)
    monkeypatch.setattr(module, "_active_allowlist", set)

    assert module._run_gate() == 0
    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted == report
    assert emitted["_meta"]["requirements_lock_sha256"] == state.sha256


def test_gate_emits_valid_evidence_before_returning_blocking_failure(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "pip-audit-report.json"
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    raw_report = _report(_dependency(vulnerabilities=[_vulnerability()]))
    report = module._with_provenance(
        raw_report,
        source="online-osv",
        lock_state=state,
        generated_at=FIXED_NOW,
        audited_at=FIXED_NOW,
        pip_audit_exit_code=1,
    )
    monkeypatch.setattr(module, "OUTPUT", output)
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state: report)
    monkeypatch.setattr(module, "_active_allowlist", set)

    assert module._run_gate() == 1
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_snapshot_capture_removes_stale_target_and_leaves_none_on_failure(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "vuln-snapshot-2026-07-13.json"
    output.write_text('{"stale": true}', encoding="utf-8")
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state, source: None)

    assert module._capture_snapshot(output) == 2
    assert not output.exists()


def test_snapshot_capture_writes_validated_online_evidence(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "vuln-snapshot-2026-07-13.json"
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    report = _snapshot_report(module, state, _report(_dependency()), FIXED_NOW)
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state, source: report)

    assert module._capture_snapshot(output) == 0
    emitted = json.loads(output.read_text(encoding="utf-8"))
    assert emitted == report
    assert emitted["dependencies"] == [_dependency()]
    assert emitted["fixes"] == []


def test_snapshot_capture_preserves_trustworthy_vulnerability_exit(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    output = tmp_path / "vuln-snapshot-2026-07-13.json"
    state = _lock_state(module, tmp_path, ("example-package", "1.0.0"))
    raw_report = _report(_dependency(vulnerabilities=[_vulnerability()]))
    report = _snapshot_report(module, state, raw_report, FIXED_NOW, return_code=1)
    monkeypatch.setattr(module, "_load_current_lock", lambda: state)
    monkeypatch.setattr(module, "_run_online_audit", lambda lock_state, source: report)

    assert module._capture_snapshot(output) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["_meta"]["pip_audit_exit_code"] == 1


def test_lock_parser_rejects_unparsed_top_level_requirements(tmp_path: Path) -> None:
    module = _load_module()
    lock = tmp_path / "requirements.lock"
    lock.write_text("example-package @ https://example.invalid/package.whl\n", encoding="utf-8")

    with pytest.raises(module.ReportValidationError, match="unparsed requirement"):
        module._load_lock_state(lock)


def test_report_output_can_be_isolated_per_ci_run(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "run-specific-report.json"
    monkeypatch.setenv("FLINTTRADE_PIP_AUDIT_REPORT", str(output))

    module = _load_module()

    assert module.OUTPUT == output


def test_workflows_cannot_upload_or_refresh_stale_unvalidated_evidence() -> None:
    root = Path(__file__).resolve().parents[2]
    supply_chain = (root / ".github" / "workflows" / "supply-chain.yml").read_text(encoding="utf-8")
    refresh = (root / ".github" / "workflows" / "refresh-vuln-snapshot.yml").read_text(encoding="utf-8")

    remove_index = supply_chain.index("Remove stale pip-audit evidence from checkout")
    setup_index = supply_chain.index("actions/setup-python@v5", remove_index)
    audit_index = supply_chain.index("pip-audit (allowlist + offline fallback)")
    upload_index = supply_chain.index("Upload newly generated pip-audit evidence")
    assert remove_index < setup_index < audit_index < upload_index
    assert "id: pip_audit" in supply_chain
    assert "always() && steps.pip_audit.outcome != 'skipped'" in supply_chain
    assert "runner.temp }}/flinttrade-pip-audit-${{ github.run_id }}-${{ github.run_attempt }}.json" in supply_chain
    assert "if-no-files-found: error" in supply_chain
    assert 'python scripts/pip-audit-with-allowlist.py --snapshot-output "$SNAPSHOT"' in refresh
    assert 'rm -f "$SNAPSHOT"' in refresh
