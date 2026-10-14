"""Supply-chain setup must select a published floor interpreter on each runner."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = json.loads((Path(__file__).parent / "fixtures/toolchain-2026-10-14.json").read_text())


@pytest.mark.parametrize(
    "job_name",
    [
        "changed-surfaces",
        "python-audit",
        "node-audit",
        "transitive-licences",
        "windows-acl-test",
        "cross-platform-smoke",
        "cla-gpg-binding",
    ],
)
def test_supply_chain_selects_a_published_floor_and_binds_uv(job_name):
    workflow = yaml.safe_load((ROOT / ".github/workflows/supply-chain.yml").read_text())
    job = workflow["jobs"][job_name]
    setup = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/setup-python@"))
    matrix = job.get("strategy", {}).get("matrix", {})
    runners = matrix.get("os", [job["runs-on"]])
    floor = tomllib.loads((ROOT / "flint.toml").read_text())["requirements"]["python_requires"].removeprefix(">=")
    for runner in runners:
        effective_env = {**workflow["env"], **job.get("env", {})}
        if effective_env.get("UV_PYTHON") == "${{ matrix.python }}":
            effective_env["UV_PYTHON"] = next(row["python"] for row in matrix["include"] if row["os"] == runner)
        selected = str(setup["with"]["python-version"])
        if selected.startswith("${{ env."):
            selected = effective_env[selected.removeprefix("${{ env.").removesuffix(" }}")]
        assert selected.startswith(floor + ".") and re.fullmatch(r"\d+\.\d+\.\d+", selected)
        release = next(r for r in CAPTURE["python_versions"] if r["version"] == selected)
        assert release["stable"] is True
        platform, version, arch = {
            "ubuntu-26.04": ("linux", "26.04", "x64"),
            "macos-26": ("darwin", None, "arm64"),
            "windows-2025": ("win32", None, "x64"),
        }[runner]
        assert any(
            f["platform"] == platform
            and f["arch"] == arch
            and (version is None or f.get("platform_version") == version)
            for f in release["files"]
        ), (job_name, runner, selected)
        available = [
            r["version"]
            for r in CAPTURE["python_versions"]
            if r["stable"]
            and r["version"].startswith(floor + ".")
            and any(
                f["platform"] == platform
                and f["arch"] == arch
                and (version is None or f.get("platform_version") == version)
                for f in r["files"]
            )
        ]
        assert selected == max(available, key=lambda value: tuple(map(int, value.split("."))))
        if any("uv sync" in s.get("run", "") for s in job["steps"]):
            assert effective_env["UV_PYTHON"] == selected
            assert effective_env["UV_PYTHON_DOWNLOADS"] == "never"


def test_supply_chain_uv_actions_use_the_exact_managed_pin():
    workflow = yaml.safe_load((ROOT / ".github/workflows/supply-chain.yml").read_text())
    manifest = json.loads((ROOT / "packages/apps/desktop/resources/bootstrap/tool-manifest.json").read_text())
    steps = [
        step for job in workflow["jobs"].values() for step in job["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]
    assert len(steps) == 3
    for step in steps:
        assert step.get("with", {}).get("version") == manifest["uv"]["version"]


@pytest.mark.parametrize(
    "job_name",
    [
        "node-audit",
        "transitive-licences",
        "python-audit",
    ],
)
@pytest.mark.skipif(sys.platform == "win32", reason="These three audited jobs execute POSIX shells on Ubuntu.")
def test_supply_chain_shell_dispatch_keeps_the_selected_python(tmp_path, job_name):
    """Execute committed shell commands with inert external tools, including errors."""
    import os
    import subprocess

    workflow = yaml.safe_load((ROOT / ".github/workflows/supply-chain.yml").read_text())
    job = workflow["jobs"][job_name]
    tools = tmp_path / "bin"
    tools.mkdir()
    log = tmp_path / "calls.jsonl"
    shim = (
        f"#!{sys.executable}\n"
        "import json,os,pathlib,sys\n"
        'record={"tool":pathlib.Path(sys.argv[0]).name,"args":sys.argv[1:],'
        '"python":os.environ.get("UV_PYTHON"),"downloads":os.environ.get("UV_PYTHON_DOWNLOADS")}\n'
        'with open(os.environ["DISPATCH_LOG"],"a") as f: f.write(json.dumps(record)+"\\n")\n'
        'raise SystemExit(23 if os.environ.get("FAIL_TOOL")==record["tool"] else 0)\n'
    )
    for name in ("rm", "python", "pip", "uv", "pnpm", "node", "pip-licenses"):
        tool = tools / name
        tool.write_text(shim)
        tool.chmod(0o700)
    commands = [s["run"] for s in job["steps"] if "run" in s]
    shell = "\n".join(commands).replace("${{ runner.temp }}", str(tmp_path))
    shell = shell.replace("${{ github.run_id }}", "fixture").replace("${{ github.run_attempt }}", "1")
    env = {**os.environ, **workflow["env"], **job.get("env", {}), "PATH": str(tools), "DISPATCH_LOG": str(log)}
    result = subprocess.run(["/bin/sh", "-ec", shell], cwd=tmp_path, env=env, check=False)
    assert result.returncode == 0
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls and all(c["python"] == "3.12.15" and c["downloads"] == "never" for c in calls)
    assert any(c["tool"] == "pip" and c["args"][:2] == ["install", "--require-hashes"] for c in calls)
    if job_name == "python-audit":
        assert any(c["tool"] == "uv" and c["args"] == ["sync", "--frozen"] for c in calls)
        assert any(c["tool"] == "python" and c["args"] == ["scripts/pip-audit-with-allowlist.py"] for c in calls)
    if job_name == "node-audit":
        assert any(c["tool"] == "pnpm" and c["args"] == ["install", "--frozen-lockfile"] for c in calls)
        assert any(c["tool"] == "python" and c["args"] == ["scripts/pnpm-audit-with-allowlist.py"] for c in calls)
    # Each observed external-tool boundary must still stop the shell on failure.
    for name in sorted({c["tool"] for c in calls}):
        log.unlink()
        result = subprocess.run(["/bin/sh", "-ec", shell], cwd=tmp_path, env={**env, "FAIL_TOOL": name}, check=False)
        assert result.returncode == 23
        failed_calls = [json.loads(line) for line in log.read_text().splitlines()]
        first = next(i for i, c in enumerate(calls) if c["tool"] == name)
        assert failed_calls == calls[: first + 1]


def test_unavailable_old_patch_is_the_captured_hosted_failure():
    old = next(r for r in CAPTURE["python_versions"] if r["version"] == "3.12.8")
    assert not any(
        f["platform"] == "linux" and f["arch"] == "x64" and f.get("platform_version") == "26.04" for f in old["files"]
    )
