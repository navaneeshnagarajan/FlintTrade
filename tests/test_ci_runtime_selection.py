"""Exercise public runtime selection and real workflow shell seams."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
import pytest
import shlex
import runpy
import os

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/ci_runtime.py"
WORKFLOW = ROOT / ".github/workflows/test.yml"
NODE_JOBS = (
    "node-core-tests",
    "node-widget-tests-1",
    "node-widget-tests-2a",
    "node-widget-tests-2b",
    "node-widget-tests-3",
    "electron-desktop-tests",
    "terminal-e2e-infra-self-tests",
)


def test_runtime_outputs_come_from_committed_bootstrap_and_package_manager():
    result = subprocess.run([sys.executable, CLI, "versions"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    versions = json.loads(result.stdout)
    manifest = json.loads((ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json").read_text())
    package = json.loads((ROOT / "package.json").read_text())
    shell = (ROOT / "packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.sh").read_text()
    assert f"export UV_PYTHON={versions['python-current']}" in shell
    assert versions["node-current"] == manifest["node"]["version"]
    assert versions["uv-current"] == manifest["uv"]["version"]
    assert versions["pnpm-current"] == package["packageManager"].split("@", 1)[1].split("+", 1)[0]
    assert versions["pnpm-current"] == manifest["pnpm"]["version"]


def test_public_isolator_has_portable_explicit_paths_and_no_mutable_source_flag():
    source = ROOT / "tools/acceptance/isolated.py"
    assert source.is_file(), "No public portable no-egress launcher exists"
    result = subprocess.run([sys.executable, source, "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for option in ["--source", "--state-root", "--assets", "--node-root", "--pnpm", "--pnpm-root", "--uv"]:
        assert option in result.stdout
    assert "--js" not in result.stdout
    text = source.read_text()
    assert not re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+|\.local/(?:specs|agent-context)/[A-Za-z0-9_.-]+", text)
    for flag in ["--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "--clearenv"]:
        assert flag in text


def test_verifier_records_actual_python_and_refuses_wrong_selection(tmp_path):
    actual = ".".join(map(str, sys.version_info[:3]))
    for expected, code in [(actual, 0), ("0.0.0", 1)]:
        output = tmp_path / (expected + ".json")
        result = subprocess.run(
            [sys.executable, CLI, "verify", "--tool", "python", "--expected", expected, "--output", output],
            capture_output=True,
            text=True,
        )
        assert result.returncode == code, result.stdout + result.stderr
        receipt = json.loads(output.read_text())
        assert receipt["actual"] == actual
        assert receipt["expected"] == expected
        assert receipt["matches"] is (code == 0)
        assert receipt["executable"] == sys.executable


def test_original_jobs_keep_floor_and_current_matrix_without_test_filters():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for name in ["python-invariants", "python-shards", *NODE_JOBS]:
        job = jobs[name]
        assert job["strategy"]["matrix"]["runtime"] == ["floor", "current"], name
        assert job["strategy"]["fail-fast"] is False
        if name != "python-shards":
            assert f"&& '{name}'" in job["name"], "Original required context must remain"
        assert "continue-on-error" not in job
        selected = next(step for step in job["steps"] if step.get("id") == "runtime")
        tool = "python" if name.startswith("python") else "node"
        floor = "3.12" if tool == "python" else "22"
        expression = selected["with"][tool + "-version"]
        assert f"matrix.runtime == 'floor' && '{floor}'" in expression
        assert f"needs.changed-surfaces.outputs.{tool}-current" in expression
        assert any("scripts/ci_runtime.py verify" in step.get("run", "") for step in job["steps"])
    assert jobs["python-shards"]["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    upload = next(
        step
        for step in jobs["python-shards"]["steps"]
        if step.get("name") == "Upload Python timing and failure evidence"
    )
    assert "${{ matrix.runtime }}" in upload["with"]["name"]


def test_required_summary_propagates_current_node_matrix_failures():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    job = jobs["python-tests"]
    assert set(NODE_JOBS) <= set(job["needs"]), "Current Node failures must reach an existing required context"
    step = next(step for step in job["steps"] if step.get("name") == "Require every selected Node runtime matrix")
    script = "\n".join(step["run"].splitlines()[1:-1])
    for selected in ["true", "false"]:
        baseline: dict[str, object] = {name: {"result": "success" if selected == "true" else "skipped"} for name in NODE_JOBS}
        baseline["changed-surfaces"] = {"outputs": {"terminal": selected, "desktop": selected}}
        for failing in [None, *NODE_JOBS]:
            states = json.loads(json.dumps(baseline))
            if failing:
                states[failing]["result"] = "failure"
            result = subprocess.run(
                [sys.executable, "-c", script], env={"MATRIX_RESULTS": json.dumps(states)},
                capture_output=True, text=True,
            )
            assert result.returncode == (1 if failing else 0), result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu Actions shell semantics; native-independent argv controls run everywhere')
def test_real_workflow_sync_command_binds_selected_python(tmp_path):
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    shim = tmp_path / "uv"
    log = tmp_path / "argv.json"
    shim.write_text(
        "#!"
        + sys.executable
        + '\nimport json,os,sys\nfrom pathlib import Path\nPath(os.environ["LOG"]).write_text(json.dumps(sys.argv[1:]))\n'
    )
    shim.chmod(0o755)
    for name in ["python-invariants", "python-shards"]:
        commands = [step["run"] for step in jobs[name]["steps"] if step.get("run", "").startswith("uv sync ")]
        assert len(commands) == 1
        for interpreter in ['/selected/python3.12', '/selected/python' + runpy.run_path(str(CLI))['versions']()['python-current']]:
            command = commands[0].replace("${{ steps.runtime.outputs.python-path }}", interpreter)
            result = subprocess.run(
                ["/bin/sh", "-eu", "-c", command],
                env={"PATH": str(tmp_path), "LOG": str(log)},
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            argv = json.loads(log.read_text())
            assert "--python" in argv, "setup-python alone does not bind uv resolution"
            assert argv[argv.index("--python") + 1] == interpreter
            assert "--frozen" in argv
            if name == "python-shards":
                assert argv[argv.index("--extra") + 1] == "ml"


@pytest.mark.parametrize('interpreter', ['/selected python/bin/python', r'C:\Selected Python\python.exe'])
def test_sync_argv_preserves_posix_and_windows_interpreter_identity(interpreter):
    # Shell parsing is the workflow's Ubuntu contract; execution here needs only
    # the current platform's Python, never POSIX shims or a simulated Windows OS.
    jobs = yaml.safe_load(WORKFLOW.read_text())['jobs']
    for name in ['python-invariants', 'python-shards']:
        command = next(s['run'] for s in jobs[name]['steps'] if s.get('run', '').startswith('uv sync '))
        argv = shlex.split(command.replace('${{ steps.runtime.outputs.python-path }}', interpreter))
        assert argv[0] == 'uv'
        child = subprocess.run([sys.executable, '-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', *argv[1:]],
                               env=dict(os.environ), capture_output=True, text=True)
        assert child.returncode == 0, child.stderr
        observed = json.loads(child.stdout)
        assert observed[observed.index('--python') + 1] == interpreter
        assert '--frozen' in observed
        if name == 'python-shards':
            assert observed[observed.index('--extra') + 1] == 'ml'
