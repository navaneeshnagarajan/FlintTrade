"""Replay official Current/LTS metadata through the real freshness gate."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = json.loads((Path(__file__).parent / "fixtures/toolchain-2026-10-14.json").read_text())


@pytest.fixture
def gate(monkeypatch):
    spec = importlib.util.spec_from_file_location("current_release_gate", ROOT / "scripts/check-toolchain-freshness.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    class CapturedDate(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 14)

    monkeypatch.setattr(module, "dt", SimpleNamespace(date=CapturedDate, datetime=dt.datetime, UTC=dt.UTC))
    responses = {
        module._NODE_SCHEDULE_URL: CAPTURE["node_schedule"],
        module._NODE_DIST_URL: CAPTURE["node_releases"],
    }
    monkeypatch.setattr(module, "_fetch_json", lambda url, report: responses.get(url))
    return module, responses


def check(gate, target="26", pin="26.11.1", floor=">=22.22.2"):
    module, _ = gate
    report = module.Report()
    module._check_node(report, {"node_requires": floor, "node_target": target}, pin)
    return report


@pytest.mark.parametrize("target", ["24", "26"])
def test_released_current_is_not_misclassified_as_older_than_lts(gate, target):
    """v26.11.1 was published before the capture; its LTS date is still ahead."""
    report = check(gate, target=target)
    assert not report.failed, [(f.subject, f.message) for f in report.findings]
    floor = [f for f in report.findings if f.subject == "node_requires (flint.toml)"]
    assert len(floor) == 1 and floor[0].level == "note"
    assert "maintenance" in floor[0].message


def test_current_counts_inside_the_same_two_line_band(gate):
    report = check(gate, target="22", pin="22.22.3")
    failures = [f for f in report.findings if f.level == "fail"]
    assert {f.subject for f in failures} == {"node_target (flint.toml)", "node (bootstrap tool-manifest.json)"}
    assert all("26, 24" in f.message and "further back than N-1" in f.message for f in failures)
    assert not any(f.level == "fail" and f.subject == "node_requires (flint.toml)" for f in report.findings)


@pytest.mark.parametrize(
    ("target", "pin", "message"),
    [
        ("27", "27.0.0", "not yet released"),
        ("99", "99.0.0", "not in the upstream release schedule"),
        ("26", "26.99.0", "not a published stable release"),
        ("26", "26.12.0-rc.1", "not a published stable release"),
        ("25", "25.9.0", "end of life"),
    ],
)
def test_unreleased_unknown_prerelease_and_eol_pins_remain_refused(gate, target, pin, message):
    report = check(gate, target=target, pin=pin)
    assert report.failed
    assert any(f.level == "fail" and message in f.message for f in report.findings)


@pytest.mark.parametrize("mutant", ["absent", "future-date", "prerelease-only", "future-start"])
def test_current_requires_real_publication_and_a_started_lifecycle(gate, mutant):
    import copy

    module, responses = gate
    rows = [r for r in CAPTURE["node_releases"] if not r["version"].startswith("v26.")]
    schedule = copy.deepcopy(CAPTURE["node_schedule"])
    if mutant == "future-date":
        rows.append({"version": "v26.11.1", "date": "2026-10-15"})
    if mutant == "prerelease-only":
        rows.append({"version": "v26.11.1-rc.1", "date": "2026-10-07"})
    if mutant == "future-start":
        rows = CAPTURE["node_releases"]
        schedule["v26"]["start"] = "2026-10-15"
    responses[module._NODE_DIST_URL] = rows
    responses[module._NODE_SCHEDULE_URL] = schedule
    report = check(gate)
    assert report.failed
    assert not any("further back than N-1" in f.message for f in report.findings)


def test_missing_release_index_skips_current_admission_instead_of_false_age_failure(gate):
    module, responses = gate
    responses[module._NODE_DIST_URL] = None
    report = check(gate)
    assert not report.failed
    assert report.skipped


def test_current_pin_requires_its_own_publication_date(gate):
    module, responses = gate
    responses[module._NODE_DIST_URL] = [
        *responses[module._NODE_DIST_URL],
        {"version": "v26.99.0"},
    ]
    report = check(gate, pin="26.99.0")
    assert report.failed
    assert any(
        finding.level == "fail" and "not a published stable release" in finding.message
        for finding in report.findings
    )


def test_future_and_prerelease_index_rows_do_not_warn_as_latest(gate):
    module, responses = gate
    responses[module._NODE_DIST_URL] = [
        *responses[module._NODE_DIST_URL],
        {"version": "v26.99.0", "date": "2026-10-15"},
        {"version": "v26.99.0-rc.1", "date": "2026-10-07"},
    ]
    report = check(gate)
    assert not report.failed
    assert not [f for f in report.findings if f.level == "warn"]


@pytest.mark.parametrize(("pin", "expected"), [("26.11.1", 0), ("26.99.0", 1), ("27.0.0", 1)])
def test_public_cli_reports_the_same_node_admission(tmp_path, pin, expected):
    """Keep __main__/argparse/report dispatch real; replace only upstream transport."""
    import shutil
    import subprocess

    for relative in (
        "scripts/check-toolchain-freshness.py",
        "flint.toml",
        "package.json",
        "packages/apps/desktop/resources/bootstrap/tool-manifest.json",
        "packages/core/core/src/flinttrade_core/ollama_runtime.py",
    ):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, dest)
    manifest_path = tmp_path / "packages/apps/desktop/resources/bootstrap/tool-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["node"]["version"] = pin
    manifest_path.write_text(json.dumps(manifest))
    capture = tmp_path / "metadata.json"
    capture.write_text(json.dumps(CAPTURE))
    report = tmp_path / "report.json"
    script = tmp_path / "scripts/check-toolchain-freshness.py"
    wrapper = r"""
import datetime, io, json, pathlib, runpy, sys, urllib.error, urllib.request
fixture = json.loads(pathlib.Path(sys.argv[1]).read_text())
class CapturedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 14)
datetime.date = CapturedDate

def fetch(request, **kwargs):
    if request.full_url == fixture['sources']['node_schedule']['url']:
        return io.BytesIO(json.dumps(fixture['node_schedule']).encode())
    if request.full_url == fixture['sources']['node_releases']['url']:
        return io.BytesIO(json.dumps(fixture['node_releases']).encode())
    raise urllib.error.URLError('unrelated upstream intentionally unavailable in fixture')
urllib.request.urlopen = fetch
script, report = sys.argv[2:4]
sys.argv = [script, '--json', '--report', report]
runpy.run_path(script, run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", wrapper, str(capture), str(script), str(report)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected, result.stderr + result.stdout
    document = json.loads(result.stdout)
    assert document == json.loads(report.read_text())
    assert document["failed"] is bool(expected)
    assert document["pins"]["node (bootstrap pin)"] == pin
    assert len(document["skipped"]) == 4
    if expected:
        assert any(
            f["subject"] == "node (bootstrap tool-manifest.json)" and f["level"] == "fail" for f in document["findings"]
        )


def test_declared_node_target_tracks_the_selected_managed_line():
    import tomllib

    declared = tomllib.loads((ROOT / "flint.toml").read_text())["requirements"]
    managed = json.loads((ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json").read_text())
    assert declared["node_target"] == managed["node"]["version"].split(".")[0]
    nightly = (ROOT / ".github/workflows/nightly-cross-platform.yml").read_text()
    assert f"node-version: '{declared['node_target']}'" in nightly
