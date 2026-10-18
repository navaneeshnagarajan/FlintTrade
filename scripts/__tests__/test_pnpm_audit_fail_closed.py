"""Exercise the public wrapper CLI with an inert, test-owned pnpm executable."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def run_audit(tmp_path, stdout, returncode):
    script = Path(__file__).resolve().parents[1] / "pnpm-audit-with-allowlist.py"
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    shutil.copy2(script, checkout / "scripts" / script.name)
    evidence = checkout / "pnpm-audit-report.json"
    evidence.write_text('{"old": "clean"}')
    shim = tmp_path / "pnpm"
    shim.write_text(f"#!{sys.executable}\nimport sys\nprint({stdout!r})\nsys.exit({returncode})\n")
    shim.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(checkout / "scripts" / script.name)],
        cwd=checkout, env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]},
        capture_output=True, text=True, check=False, timeout=15,
    )
    return result, evidence


@pytest.mark.parametrize("stdout,returncode", [
    ("", 0), ("", 1), ("{}", 0), ('{"error": {"code": "NETWORK"}}', 1),
    ('{"advisories": {}}', 2), ('{"advisories": {}}', 1),
    ('{"advisories": {"1": {"severity": "unknown"}}}', 0),
    ('{"vulnerabilities": {"pkg": null}}', 0), ("[]", 0), ("broken", 0),
])
def test_tooling_failure_cannot_report_clean_or_retain_stale_evidence(tmp_path, stdout, returncode):
    result, evidence = run_audit(tmp_path, stdout, returncode)
    assert result.returncode == 2
    assert "clean" not in result.stdout.lower()
    assert not evidence.exists()


@pytest.mark.parametrize("shape", ["advisories", "vulnerabilities"])
def test_explicit_valid_empty_audit_is_clean(tmp_path, shape):
    result, evidence = run_audit(tmp_path, json.dumps({shape: {}}), 0)
    assert result.returncode == 0
    assert json.loads(evidence.read_text()) == {shape: {}}
