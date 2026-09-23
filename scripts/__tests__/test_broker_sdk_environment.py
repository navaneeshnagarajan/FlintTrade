"""The managed Kotak SDK is repaired before source setup attests it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("python", [Path("/repo/.venv/bin/python"), Path("C:/repo/.venv/Scripts/python.exe")])
def test_repair_replaces_stale_distributions_then_is_idempotent(python: Path) -> None:
    from scripts.broker_sdk_environment import repair_kotakneo_environment

    state = {"kotakneoapi": {"version": "3.0.7", "direct_url": None}, "neo-api-client": {"version": "2.0.0"},
             "namespace_owners": ["kotakneoapi", "neo-api-client"]}
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        argv = list(map(str, args))
        calls.append(argv)
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(state), "")
        if argv[1:3] == ["-m", "pip"]:
            return subprocess.CompletedProcess(argv, 1, "", "No module named pip")
        if argv[:4] == ["uv", "pip", "uninstall", "--python"]:
            assert argv[4] == str(python)
            assert set(argv[5:]) == {"kotakneoapi", "neo-api-client"}
            state.clear()
            return subprocess.CompletedProcess(argv, 0, "", "")
        assert "--frozen" in argv and "--reinstall-package" in argv
        assert "kotakneoapi" in argv
        state["kotakneoapi"] = {
            "version": "3.0.7",
            "direct_url": {
                "url": "https://github.com/Kotak-Neo/kotak-neo-python.git",
                "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
            },
        }
        state["namespace_owners"] = ["kotakneoapi"]
        return subprocess.CompletedProcess(argv, 0, "", "")

    repair_kotakneo_environment(python, run=run)
    first_commands = len(calls)
    repair_kotakneo_environment(python, run=run)

    assert len(calls) == first_commands + 1  # second call probes only
    assert len([call for call in calls if "--reinstall-package" in call]) == 1


def test_interrupted_repair_fails_closed() -> None:
    from scripts.broker_sdk_environment import repair_kotakneo_environment

    commands: list[list[str]] = []

    def run(args, **_kwargs):
        argv = list(map(str, args))
        commands.append(argv)
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"neo-api-client": {"version": "2.0.0"}}), "")
        if "uninstall" in argv:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", "network interrupted")

    with pytest.raises(RuntimeError, match="sync"):
        repair_kotakneo_environment(Path("/repo/.venv/bin/python"), run=run)
    assert any("uninstall" in command for command in commands)
    assert any("--reinstall-package" in command for command in commands)


def test_remove_kotak_without_interpreter_pip_when_uv_is_available(monkeypatch) -> None:
    from scripts import broker_sdk_environment as sdk_environment

    # Make the uv branch independent of the contributor's PATH.
    monkeypatch.setattr(sdk_environment.shutil, "which", lambda name: "/fixture/uv" if name == "uv" else None)
    python = Path(sys.executable)

    commands: list[list[str]] = []

    def run(args, **_kwargs):
        argv = list(map(str, args))
        commands.append(argv)
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps({"kotakneoapi": {"version": "3.0.7"}}), "")
        if argv[1:3] == ["-m", "pip"]:
            return subprocess.CompletedProcess(argv, 1, "", "No module named pip")
        return subprocess.CompletedProcess(argv, 0, "", "")

    sdk_environment.remove_kotak_distributions(python, run=run)

    assert commands[-1] == ["uv", "pip", "uninstall", "--python", str(python),
                            "kotakneoapi", "neo-api-client"]


def test_repair_accepts_record_only_namespace_evidence(tmp_path: Path, monkeypatch) -> None:
    from scripts import ft
    from scripts.broker_sdk_environment import repair_kotakneo_environment

    real_resolver = ft.resolve_python
    resolutions = 0

    def tracked_resolver() -> str:
        nonlocal resolutions
        resolutions += 1
        return real_resolver()

    monkeypatch.setattr(ft, "resolve_python", tracked_resolver)

    dist = tmp_path / "kotakneoapi-3.0.7.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.3\nName: kotakneoapi\nVersion: 3.0.7\n")
    (dist / "RECORD").write_text("neo_api_client/__init__.py,,\n")
    package = tmp_path / "neo_api_client"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (dist / "direct_url.json").write_text(json.dumps({
        "url": "https://github.com/Kotak-Neo/kotak-neo-python.git",
        "vcs_info": {"vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"},
    }))
    python = Path(ft.resolve_python())
    commands: list[list[str]] = []

    def run(args, **kwargs):
        argv = list(map(str, args))
        commands.append(argv)
        if "-c" not in argv:
            raise AssertionError(f"Healthy RECORD-only SDK must not be reinstalled: {argv}")
        return subprocess.run(
            [str(python), "-S", "-c", argv[2]],
            env=os.environ | {"PYTHONPATH": str(tmp_path)}, **kwargs,
        )

    repair_kotakneo_environment(python, run=run)

    assert len(commands) == 1
    assert resolutions == 1


@pytest.mark.parametrize("direct_url", [
    {"url": "https://github.com:bad/Kotak-Neo/kotak-neo-python.git", "vcs_info": {"vcs": "git"}},
    {"url": "https://[broken/Kotak-Neo/kotak-neo-python.git", "vcs_info": {"vcs": "git"}},
    {"url": "https://github.com/Kotak-Neo/kotak-neo-python.git", "vcs_info": ["git"]},
])
def test_malformed_provenance_is_repairable_and_fails_closed_if_persistent(direct_url) -> None:
    from scripts.broker_sdk_environment import repair_kotakneo_environment

    commands: list[list[str]] = []
    state = {"kotakneoapi": {"version": "3.0.7", "direct_url": direct_url},
             "namespace_owners": ["kotakneoapi"]}

    def run(args, **_kwargs):
        argv = list(map(str, args))
        commands.append(argv)
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(state), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(RuntimeError, match="pinned Git distribution"):
        repair_kotakneo_environment(Path("/repo/.venv/bin/python"), run=run)
    assert any("uninstall" in command for command in commands)
    assert any("--reinstall-package" in command for command in commands)


def test_repair_refuses_unproven_namespace_ownership() -> None:
    from scripts.broker_sdk_environment import repair_kotakneo_environment

    valid_provenance = {"url": "https://github.com/Kotak-Neo/kotak-neo-python.git", "vcs_info": {
        "vcs": "git", "commit_id": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"}}
    state = {"kotakneoapi": {"version": "3.0.7", "direct_url": valid_provenance}}

    def run(args, **_kwargs):
        argv = list(map(str, args))
        if "-c" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(state), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    with pytest.raises(RuntimeError, match="exclusive namespace"):
        repair_kotakneo_environment(Path("/repo/.venv/bin/python"), run=run)


@pytest.mark.parametrize("uv_available", [True, False])
def test_native_setup_repairs_or_removes_kotak_before_attestation(monkeypatch, uv_available: bool) -> None:
    from scripts import ft

    class ReachedHook(Exception):
        pass

    calls: list[str] = []

    def hook(_python):
        calls.append("repair" if uv_available else "remove")
        raise ReachedHook

    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/Scripts/python.exe")
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/bin/uv" if name == "uv" and uv_available else None)
    monkeypatch.setattr(ft, "run", lambda *_args, **_kwargs: calls.append("install") or 0)
    monkeypatch.setattr(ft, "repair_kotakneo_environment", hook)
    monkeypatch.setattr(ft, "remove_kotak_distributions", hook)
    with pytest.raises(ReachedHook):
        ft.cmd_setup([])
    assert calls[-1] == ("repair" if uv_available else "remove")


def test_posix_source_setup_verifies_with_synced_interpreter(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$PROBE_OUTPUT"\n', encoding="utf-8")
    python.chmod(0o755)
    output = tmp_path / "probe.txt"
    env = os.environ | {"FLINTTRADE_DIR": str(tmp_path), "PROBE_OUTPUT": str(output)}

    result = subprocess.run(
        ["bash", str(repo / "infra" / "scripts" / "setup.sh"), "--verify-only"],
        env=env, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines()[:2] == ["-m", "pytest"]
