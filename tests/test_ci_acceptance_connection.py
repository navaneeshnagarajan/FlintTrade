"""Public CI connection contracts; synthetic inputs never invoke a compiler."""
import re
import json
import ast
import runpy
import hashlib
import io
import pytest
import yaml
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_uv_version_probe_retains_native_release_descriptor_and_denies_drift(tmp_path):
    # Preserve real public argparse/verify dispatch. Only the external uv process
    # is substituted with an explicitly invoked Python child on every platform.
    selected = runpy.run_path(str(ROOT / 'scripts/ci_runtime.py'))['versions']()['uv-current']
    driver = (
        "import os,runpy,shutil,subprocess,sys\n"
        "cli=sys.argv.pop(1); real=subprocess.check_output\n"
        "shutil.which=lambda tool: sys.executable\n"
        "subprocess.check_output=lambda argv,**kw: real([sys.executable,'-c','print('+repr(os.environ['UV_REPORT'])+')'],**kw)\n"
        "sys.argv[0]=cli; runpy.run_path(cli,run_name='__main__')\n"
    )
    actual = 'uv ' + selected + ' (x86_64-unknown-linux-gnu)'
    for expected, code in [(selected, 0), ('0.0.0', 1)]:
        result = subprocess.run([sys.executable, '-c', driver, ROOT / 'scripts/ci_runtime.py', 'verify', '--tool', 'uv', '--expected', expected],
                                env=dict(os.environ, UV_REPORT=actual), capture_output=True, text=True)
        assert result.returncode == code, result.stderr
        receipt = json.loads(result.stdout)
        assert receipt['actual'] == selected
        assert receipt['reported'] == actual
        assert receipt['matches'] is (code == 0)
    result = subprocess.run([sys.executable, '-c', driver, ROOT / 'scripts/ci_runtime.py', 'verify', '--tool', 'uv', '--expected', selected],
                            env=dict(os.environ, UV_REPORT='uv ' + selected + 'rc1 (synthetic)'), capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Unrecognised stable tool version' in result.stderr



@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu Actions bash dispatch; neutral CLI contracts run on every platform')
def test_ci_build_then_readonly_aggregate_propagates_both_failures(tmp_path):
    jobs = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())["jobs"]
    steps = jobs["terminal-e2e-infra-self-tests"]["steps"]
    selected = [s for s in steps if s.get("name") == "Build Reticle then run maintained offline acceptance"]
    assert len(selected) == 1, "Required browser job never invokes the maintained full aggregate"
    assert selected[0]["if"] == "matrix.runtime == 'current'"
    command = selected[0]["run"]
    assert "--no-verify" not in command and "--ci-only" not in command
    for failing, expected in [("", 0), ("reticle-build", 17), ("maintained-acceptance", 23)]:
        base = tmp_path / (failing or "success")
        source = base / "acceptance-source"
        (source / "tools/acceptance").mkdir(parents=True)
        log = base / "calls.jsonl"
        # Replace only the namespace tool, not the real workflow shell dispatch.
        (source / "tools/acceptance/isolated.py").write_text(
            "import json,os,sys\nfrom pathlib import Path\n"
            "a=sys.argv[1:]; label=a[a.index('--label')+1]\n"
            "with Path(os.environ['CALLS']).open('a') as f:f.write(json.dumps(a)+'\\n')\n"
            "if os.environ['FAIL']==label:sys.exit(17 if label=='reticle-build' else 23)\n"
            "if label=='reticle-build':\n"
            " p=Path(a[a.index('--state-root')+1])/'flinttrade-reticle-build-synthetic'/'reticle'\n"
            " (p/'package').mkdir(parents=True);(p/'consumer').mkdir()\n"
            " (p/'package/proof').write_text('synthetic output')\n"
            "else:\n"
            " p=Path(a[a.index('--source')+1]);assert (p/'tools/reticle/runtime/package/proof').read_text()=='synthetic output'\n"
        )
        env = dict(os.environ, RUNNER_TEMP=str(base), CALLS=str(log), FAIL=failing,
                   CI_NODE_ROOT="/selected/node", CI_PNPM="/selected/pnpm/bin/pnpm",
                   CI_PNPM_ROOT="/selected/pnpm", CI_UV="/selected/uv")
        result = subprocess.run(["/bin/bash", "-euo", "pipefail", "-c", command],
                                env=env, capture_output=True, text=True)
        assert result.returncode == expected, result.stdout + result.stderr
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(calls) == (1 if failing == "reticle-build" else 2)
        assert "--js" not in str(calls)
        if len(calls) == 2:
            assert "npm --prefix packages/apps/terminal run e2e" in calls[1][-1]
            assert "FLINTTRADE_E2E_PYTHON" in calls[1][-1]
            assert "FLINTTRADE_E2E_CACHE_DIR=/run/test/cache/vite" in calls[1][-1]
            assert "--case" not in calls[1][-1]


def test_native_build_is_in_required_python_matrix_with_explicit_interpreter():
    jobs = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())["jobs"]
    job = jobs["python-invariants"]
    steps = [s for s in job["steps"] if s.get("name") == "Build and import current tick_engine"]
    assert len(steps) == 1, "Cargo-only or skipped bindings are not Python ABI evidence"
    step = steps[0]
    assert "if" not in step
    assert job["strategy"]["matrix"]["runtime"] == ["floor", "current"]
    assert "python-invariants" in jobs["python-tests"]["needs"]
    command = step["run"]
    for required in ['--python "${{ steps.runtime.outputs.python-path }}"',
                     "--no-cache", "--wheel", "--config-setting=build-args=--locked",
                     "scripts/ci_runtime.py native-inputs", "scripts/ci_runtime.py native",
                     '--python "$PWD/.venv/bin/python"', "--no-deps", "--reinstall"]:
        assert required in command
    assert "hashFiles(" in step["env"]["CARGO_TARGET_DIR"]
    assert "matrix.runtime" in step["env"]["CARGO_TARGET_DIR"]



def test_native_binding_cli_binds_current_source_and_refuses_wrong_python(tmp_path):
    cli = ROOT / "scripts/ci_runtime.py"
    output = tmp_path / "inputs.json"
    before = subprocess.run([sys.executable, cli, "native-inputs", "--output", output],
                            capture_output=True, text=True)
    assert before.returncode == 0, before.stderr
    record = json.loads(output.read_text())
    assert "src/lib.rs" in record["files"]
    assert "Cargo.lock" in record["files"]
    assert "python/tick_engine/__init__.py" in record["files"]
    result = subprocess.run([sys.executable, cli, "native", "--expected", "0.0.0",
                             "--inputs", output, "--wheel", tmp_path / "missing.whl"],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert '"matches": false' in result.stdout


def test_native_binding_gate_refuses_source_drift_before_import(tmp_path):
    cli = ROOT / "scripts/ci_runtime.py"
    output = tmp_path / "inputs.json"
    result = subprocess.run([sys.executable, cli, "native-inputs", "--output", output],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    record = json.loads(output.read_text())
    record["files"]["src/lib.rs"] = "0" * 64
    output.write_text(json.dumps(record))
    result = subprocess.run([sys.executable, cli, "native", "--expected", ".".join(map(str, sys.version_info[:3])),
                             "--inputs", output, "--wheel", tmp_path / "missing.whl"],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "Native source changed during build" in result.stderr



@pytest.mark.skipif(sys.platform != 'linux', reason='Actual Ubuntu shell dispatch; portable argv contract runs separately')
def test_readonly_vite_dispatch_uses_runner_and_external_cache(tmp_path):
    config = (ROOT / "packages/apps/terminal/playwright.config.ts").read_text()
    value = re.search(r"command: (.+),", config).group(1)
    command = ast.literal_eval(value)
    shim = tmp_path / "pnpm"
    shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    shim.chmod(0o755)
    result = subprocess.run(["/bin/sh", "-eu", "-c", command],
                            env={"PATH": str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    argv = result.stdout.splitlines()
    assert "--configLoader" in argv, "Vite's default loader writes into read-only source"
    assert argv[argv.index("--configLoader") + 1] == "runner"
    assert "--strictPort" in argv
    vite = (ROOT / "packages/apps/terminal/vite.config.ts").read_text()
    assert 'cacheDir: process.env.FLINTTRADE_E2E_CACHE_DIR' in vite
    demo = (ROOT / "packages/apps/terminal/e2e/start-public-demo.ts").read_text()
    assert demo.count('"--configLoader", "runner"') == 2


def test_readonly_vite_argv_is_platform_neutral():
    import shlex
    config = (ROOT / 'packages/apps/terminal/playwright.config.ts').read_text()
    command = ast.literal_eval(re.search(r'command: (.+),', config).group(1))
    argv = shlex.split(command)
    result = subprocess.run([sys.executable, '-c', 'import json,sys;print(json.dumps(sys.argv[1:]))', *argv[1:]],
                            capture_output=True, text=True)
    assert result.returncode == 0
    actual = json.loads(result.stdout)
    assert argv[0] == 'pnpm' and actual[:2] == ['exec', 'vite']
    assert actual[actual.index('--configLoader') + 1] == 'runner'
    assert '--strictPort' in actual
    assert 'cacheDir: process.env.FLINTTRADE_E2E_CACHE_DIR' in (ROOT / 'packages/apps/terminal/vite.config.ts').read_text()



def test_public_archive_acquisition_checks_bytes_before_publication(tmp_path, monkeypatch):
    script = ROOT / "tools/reticle/acquire.py"
    assert script.is_file(), "Public primary-archive acquisition is not connected"
    module = runpy.run_path(str(script))
    download = module["download"]
    payload = b"synthetic archive bytes"
    digest = hashlib.sha256(payload).hexdigest()
    class Response(io.BytesIO):
        def geturl(self):
            return "https://registry.npmjs.org/synthetic/-/synthetic-1.tgz"
    class Transport:
        def open(self, *args, **kwargs):
            return Response(payload)
    monkeypatch.setattr(module["urllib"].request, "build_opener", lambda *handlers: Transport())
    target = tmp_path / "archive.tgz"
    url = "https://registry.npmjs.org/synthetic/-/synthetic-1.tgz"
    download(url, "sha256", bytes.fromhex(digest), target)
    assert target.read_bytes() == payload
    target.write_bytes(b"corrupted cache")
    with pytest.raises(RuntimeError, match="digest"):
        download(url, "sha256", bytes.fromhex(digest), target)
    assert target.read_bytes() == b"corrupted cache"
    target.unlink()
    with pytest.raises(RuntimeError, match="digest"):
        download(url, "sha256", bytes.fromhex("0" * 64), target)
    assert not target.exists()
    for url in ["http://registry.npmjs.org/a.tgz", "https://example.invalid/a.tgz",
                "https://user:pass@registry.npmjs.org/a.tgz"]:
        with pytest.raises(RuntimeError, match="primary"):
            download(url, "sha256", bytes.fromhex(digest), target)
    assert not target.exists()



def test_portable_launcher_contract_does_not_publish_operator_paths():
    for name in ["tools/acceptance/isolated.py", "tests/test_ci_runtime_selection.py"]:
        text = (ROOT / name).read_text()
        assert not re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+", text), name
        assert not re.search(r"\.local/(?:specs|agent-context)/[A-Za-z0-9_.-]+", text), name


def test_portable_launcher_refuses_private_source_roots(tmp_path):
    for forbidden in [".git", ".local", "graphify-out"]:
        source = tmp_path / forbidden.strip(".")
        source.mkdir()
        (source / forbidden).mkdir()
        argv = [sys.executable, str(ROOT / "tools/acceptance/isolated.py"), "--label", "synthetic"]
        for name in ["source", "state-root", "assets", "node-root", "pnpm", "pnpm-root", "uv"]:
            argv += ["--" + name, str(source if name == "source" else tmp_path)]
        result = subprocess.run([*argv, "--", sys.executable, "-c", "pass"], capture_output=True, text=True)
        assert result.returncode == 2
        assert "Source-only input required" in result.stderr
