"""Exercise public desktop dispatch and real package-script chaining with harmless tools."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = Path("packages/apps/desktop")
STEPS = [
    "install", "clean-electron-output.mjs", "generate-bootstrap-tool-manifest.mjs",
    "build-windows-job-supervisor.mjs", "build-atomic-promoter.mjs", "tsc", "vitest",
    "bundle-electron.mjs", "run-electron-builder.mjs", "verify-electron-package.mjs",
]
TARGETS = [
    ("Windows", "AMD64", "pack:win", ["--win", "nsis", "--x64"]),
    ("Darwin", "arm64", "pack:mac", ["--mac", "dmg", "--universal"]),
    ("Linux", "x86_64", "pack:linux:x64", ["--linux", "AppImage", "--x64"]),
    ("Linux", "aarch64", "pack:linux:arm64", ["--linux", "AppImage", "--arm64"]),
]
pytestmark = [pytest.mark.unit, pytest.mark.skipif(os.name == "nt", reason="Fixture tools use POSIX shebangs")]


@pytest.fixture
def packaging_checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Use the real runner and metadata; replace only external build/install executables."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("ft.py", "broker_sdk_environment.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    package = tmp_path / DESKTOP
    package.mkdir(parents=True)
    shutil.copyfile(ROOT / DESKTOP / "package.json", package / "package.json")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Shell input is trusted, copied repository metadata, never user input. This
    # deliberately exercises the same && failure boundaries as a package manager.
    tool_source = (
        f"#!{sys.executable}\n"
        "import json, os, pathlib, subprocess, sys\n"
        "tool = pathlib.Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "if tool == 'corepack':\n"
        "    assert args.pop(0) == 'pnpm'\n"
        "    if args[0] == '--dir':\n"
        "        directory = pathlib.Path(args[1])\n"
        "        assert args[2] == 'run'\n"
        "        command = json.loads((directory / 'package.json').read_text())['scripts'][args[3]]\n"
        "        raise SystemExit(subprocess.run(command, shell=True, cwd=directory).returncode)\n"
        "    assert args == ['install', '--frozen-lockfile']\n"
        "    step = 'install'\n"
        "elif tool == 'node':\n"
        "    step = pathlib.Path(args[0]).name\n"
        "else:\n"
        "    step = tool\n"
        "with open(os.environ['COMMAND_LOG'], 'a') as log:\n"
        "    log.write(json.dumps({'step': step, 'args': args}) + '\\n')\n"
        "raise SystemExit(29 if os.environ.get('FAIL_STEP') == step else 0)\n"
    )
    for name in ("corepack", "node", "tsc", "vitest"):
        tool = bin_dir / name
        tool.write_text(tool_source, encoding="utf-8")
        tool.chmod(0o755)
    env = os.environ | {
        "PATH": str(bin_dir), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "FAIL_STEP": "",
        "FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "workspace"), "COMMAND_LOG": str(tmp_path / "commands.jsonl"),
    }
    return tmp_path, env


def _run_package(checkout: tuple[Path, dict[str, str]], system: str = "Linux", machine: str = "x86_64"):
    root, env = checkout
    # Simulate target selection only. __main__, subprocesses and shell short-circuiting stay real.
    launch = (
        "import platform, runpy, sys\n"
        "system, machine = sys.argv[1:3]\n"
        "platform.system = lambda: system\n"
        "platform.machine = lambda: machine\n"
        "sys.argv = ['scripts/ft.py', 'desktop-package']\n"
        "runpy.run_path('scripts/ft.py', run_name='__main__')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", launch, system, machine], cwd=root, env=env,
        text=True, capture_output=True, check=False, timeout=20,
    )
    return result, _commands(env)


def _commands(env: dict[str, str]) -> list[dict]:
    log = Path(env["COMMAND_LOG"])
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _assert_preparation_gates(commands: list[dict]) -> None:
    args = {command["step"]: command["args"] for command in commands}
    assert args["generate-bootstrap-tool-manifest.mjs"] == ["scripts/generate-bootstrap-tool-manifest.mjs", "--check"]
    assert args["tsc"] == ["-p", "tsconfig.electron.json", "--noEmit"]
    assert args["vitest"] == ["run", "--config", "vitest.electron.config.ts"]
    for script in ("build-windows-job-supervisor.mjs", "build-atomic-promoter.mjs",
                   "bundle-electron.mjs", "verify-electron-package.mjs"):
        assert args[script] == [f"scripts/{script}"]


@pytest.mark.parametrize("system,machine,script,target", TARGETS)
def test_public_desktop_package_prepares_once_and_keeps_every_gate(
    system: str, machine: str, script: str, target: list[str], packaging_checkout,
) -> None:
    result, commands = _run_package(packaging_checkout, system, machine)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [command["step"] for command in commands] == STEPS
    assert commands[0]["args"] == ["install", "--frozen-lockfile"]
    _assert_preparation_gates(commands)
    builder = next(command["args"] for command in commands if command["step"] == "run-electron-builder.mjs")
    assert builder[1:4] == target
    assert builder[4:6] == ["--publish", "never"]
    if script == "pack:mac":
        assert builder[6:] == ["--config.mac.identity=-", "--config.mac.hardenedRuntime=false"]
    assert "OK Electron package" in result.stdout


@pytest.mark.parametrize("failed_step", STEPS)
def test_public_desktop_package_stops_at_any_failed_gate(failed_step: str, packaging_checkout) -> None:
    root, env = packaging_checkout
    result, commands = _run_package((root, env | {"FAIL_STEP": failed_step}))
    assert result.returncode == 29, result.stdout + result.stderr
    assert [command["step"] for command in commands] == STEPS[:STEPS.index(failed_step) + 1]
    assert "OK Electron package" not in result.stdout


@pytest.mark.parametrize("script", [target[2] for target in TARGETS] + ["pack:dir", "pack:dir:win"])
def test_standalone_pack_entrypoints_prepare_and_verify_without_prior_build(script: str, packaging_checkout) -> None:
    root, env = packaging_checkout
    result = subprocess.run(
        [str(root / "bin/corepack"), "pnpm", "--dir", str(DESKTOP), "run", script], cwd=root, env=env,
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = _commands(env)
    assert [command["step"] for command in commands] == STEPS[1:]
    _assert_preparation_gates(commands)
