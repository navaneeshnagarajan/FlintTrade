"""Opt-in Laya sidecar: loopback, pinned package, and the status probe."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from flinttrade_core.health_routes import health_bp
from flinttrade_core.laya_runtime import (
    CPU_TORCH_INDEX,
    LAYA_BIND_HOST,
    LAYA_DOWNLOAD_BOOTSTRAP,
    LAYA_DOWNLOAD_LOG,
    LAYA_SERVE_REQUIREMENT,
    LAYA_WATCH_INTERVAL_SECONDS,
    LAYA_WEIGHTS_DRIFT_LOG,
    LAYA_WEIGHTS_LOG,
    ArtifactCheck,
    LayaRuntime,
    LayaRuntimeError,
    attach_from_environment,
    constraint_lines_with_extras,
    cpu_torch_command,
    install_command,
    install_commands,
    main,
    find_pinned_weight,
    set_process_runtime,
    sidecar_constraints_path,
    snapshot_weight_path,
    verify_installed_model,
    verify_weight_file,
    venv_python,
)
from flinttrade_core.service_providers import EvidenceUseScope
from flinttrade_engine.laya import (
    DecisionStatus,
    Proposal,
    laya_reason_detail,
    laya_reason_tooltip,
    process_laya,
    reset_process_laya_for_tests,
)
from flinttrade_engine.laya_decision import LayaQualification, load_policy, publish_probe


class _Process:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        return self.returncode


def _healthy(**overrides: object) -> dict[str, object]:
    policy = load_policy()
    payload: dict[str, object] = {
        "status": "ok",
        "loaded": [policy.checkpoint],
        "revisions": {policy.checkpoint: policy.revision},
        "sha256": policy.sha256,
        "device": "cpu",
        "cpu_fallbacks": {policy.checkpoint: {"count": 0}},
    }
    payload.update(overrides)
    return payload


def _unchecked_ready() -> ArtifactCheck:
    """A test double that skips the on-disk pin. The launch still stays offline."""
    policy = load_policy()
    return ArtifactCheck(ok=True, reason=None, revision=policy.revision, sha256=policy.sha256)


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    policy = load_policy()
    _plant_snapshot(tmp_path, monkeypatch, extra=None)
    _accept_pinned_digests(monkeypatch, policy)
    created: list[_Process] = []
    envs: list[dict[str, str]] = []
    commands: list[list[str]] = []

    def factory(argv: list[str], env: dict[str, str]) -> _Process:
        envs.append(dict(env))
        process = _Process()
        created.append(process)
        return process

    def installer(venv: Path, command: list[str]) -> None:
        commands.append(command)
        assert venv == tmp_path / "runtime" / "laya" / "venv"

    sidecar = LayaRuntime(
        tmp_path,
        process_factory=factory,
        installer=installer,
        health_reader=lambda _url: _healthy(),
    )
    sidecar.created = created  # type: ignore[attr-defined]
    sidecar.envs = envs  # type: ignore[attr-defined]
    sidecar.commands = commands  # type: ignore[attr-defined]
    yield sidecar
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_install_command_pins_the_sidecar_venv_not_the_main_interpreter(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    command = install_command(venv)
    torch = cpu_torch_command(venv)
    assert LAYA_SERVE_REQUIREMENT in command
    assert command[0] == str(venv_python(venv))
    assert torch[0] == str(venv_python(venv))
    assert CPU_TORCH_INDEX in torch
    assert Path(command[0]) != Path(sys.executable)
    constraints = sidecar_constraints_path()
    pinned = constraints.read_text(encoding="utf-8")
    assert "torch==2.14.0+cpu" in pinned
    assert "laya==0.3.21" in pinned
    assert constraint_lines_with_extras(pinned) == []
    assert LAYA_SERVE_REQUIREMENT == "laya[serve]==0.3.21"
    assert CPU_TORCH_INDEX in pinned
    assert str(constraints) in torch
    assert torch[-1] == "torch"
    cpu = install_commands(venv, accelerator="cpu")
    assert cpu[0] == torch
    assert cpu[1][-1] == LAYA_SERVE_REQUIREMENT
    assert str(constraints) in cpu[1]
    cuda = install_commands(venv, accelerator="cuda")
    assert all(CPU_TORCH_INDEX not in part and str(constraints) not in part for command in cuda for part in command)
    assert cuda[0][-1] == "torch"
    root = Path(__file__).resolve().parents[4]
    assert "laya" not in (root / "packages/core/core/pyproject.toml").read_text(encoding="utf-8")
    assert "torch" not in (root / "packages/core/core/pyproject.toml").read_text(encoding="utf-8")
    assert "unsloth" not in (root / "packages/core/core/src/flinttrade_core/laya_runtime.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
def test_start_binds_loopback_mints_a_key_and_pins_the_checkpoint(runtime: LayaRuntime) -> None:
    runtime.install()
    runtime.start()
    env = runtime.envs[-1]  # type: ignore[attr-defined]
    commands = runtime.commands  # type: ignore[attr-defined]
    assert CPU_TORCH_INDEX in commands[0]
    assert commands[0][-1] == "torch"
    assert commands[-1][-1] == LAYA_SERVE_REQUIREMENT
    assert env["LAYA_HOST"] == "127.0.0.1"
    assert env["LAYA_DEVICE"] == "cpu"
    assert "LAYA_REVISION" not in env
    assert "LAYA_MODELS" not in env
    assert load_policy().sha256 in env["LAYA_SHA256_DIGESTS"]
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["LAYA_WEIGHTS_PATH"]
    assert env["LAYA_API_KEY"]
    first_key = env["LAYA_API_KEY"]
    runtime.publish_status()
    runtime.start()
    second = runtime.envs[-1]  # type: ignore[attr-defined]
    assert second["HF_HUB_OFFLINE"] == "1"
    assert second["TRANSFORMERS_OFFLINE"] == "1"
    assert second["LAYA_API_KEY"] != first_key
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    assert process_laya().effective_status("live") is DecisionStatus.DOWN


@pytest.mark.unit
def test_runtime_rejects_a_public_bind_and_an_unqualified_device(tmp_path: Path) -> None:
    with pytest.raises(LayaRuntimeError, match="127.0.0.1"):
        LayaRuntime(tmp_path, host="0.0.0.0")
    with pytest.raises(LayaRuntimeError, match="CPU"):
        LayaRuntime(tmp_path, device="cuda")


@pytest.mark.unit
def test_stop_terminates_the_sidecar_and_records_down(runtime: LayaRuntime) -> None:
    runtime.install()
    runtime.start()
    key_path = runtime.runtime_root / "api.key"
    assert key_path.is_file()
    assert key_path.read_text(encoding="utf-8")
    process = runtime.created[-1]  # type: ignore[attr-defined]
    runtime.stop()
    assert process.terminated is True
    assert not key_path.exists()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().note_heartbeat() is DecisionStatus.DOWN


@pytest.mark.unit
def test_health_ok_is_ready_for_practice_only() -> None:
    engine = process_laya()
    publish_probe(engine, _healthy())
    assert engine.effective_status("practice") is DecisionStatus.READY
    assert engine.effective_status("live") is DecisionStatus.DOWN
    assert engine.note_heartbeat() is DecisionStatus.DOWN


@pytest.mark.unit
def test_cpu_fallback_on_a_requested_accelerator_is_degraded() -> None:
    engine = process_laya()
    payload = _healthy(device="cpu", cpu_fallbacks={"english": {"count": 2}})
    status = publish_probe(engine, payload, requested_device="cuda")
    assert status is DecisionStatus.DEGRADED
    assert engine.effective_status("practice") is DecisionStatus.DEGRADED


@pytest.mark.unit
def test_unreachable_probe_is_down() -> None:
    engine = process_laya()
    engine.set_status(DecisionStatus.READY)
    publish_probe(engine, None)
    assert engine.status is DecisionStatus.DOWN
    assert engine.effective_status("practice") is DecisionStatus.DOWN


@pytest.mark.unit
def test_missing_health_digest_is_down() -> None:
    engine = process_laya()
    payload = _healthy()
    payload.pop("sha256")
    publish_probe(engine, payload)
    assert engine.status is DecisionStatus.DOWN
    payload = _healthy(sha256="")
    publish_probe(engine, payload)
    assert engine.status is DecisionStatus.DOWN


@pytest.mark.unit
def test_digest_mismatch_on_the_probe_is_down() -> None:
    engine = process_laya()
    publish_probe(engine, _healthy(sha256="cd" * 32))
    assert engine.status is DecisionStatus.DOWN


@pytest.mark.unit
def test_live_qualification_requires_the_exact_pin() -> None:
    policy = load_policy()
    engine = process_laya()
    practice_only = LayaQualification(
        revision=policy.revision,
        policy_version=policy.version,
        sha256=policy.sha256,
        scope=EvidenceUseScope.PRACTICE_QUALIFICATION,
    )
    engine.set_qualification(practice_only)
    publish_probe(engine, _healthy())
    assert engine.effective_status("practice") is DecisionStatus.READY
    assert engine.effective_status("live") is DecisionStatus.DOWN

    engine.set_qualification(
        LayaQualification(
            revision=policy.revision,
            policy_version=policy.version,
            sha256=policy.sha256,
            scope=EvidenceUseScope.LIVE_DECISION,
        )
    )
    publish_probe(engine, _healthy())
    assert engine.effective_status("live") is DecisionStatus.READY
    assert engine.note_heartbeat() is DecisionStatus.READY


@pytest.mark.unit
def test_stop_discards_an_in_flight_health_probe(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def reader(_url: str) -> dict[str, object]:
        started.set()
        assert release.wait(2)
        return _healthy()

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        health_reader=reader,
        artifact_checker=_unchecked_ready,
    )
    runtime.start()
    worker = threading.Thread(target=runtime.publish_status)
    worker.start()
    assert started.wait(2)
    runtime.stop()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().effective_status("practice") is DecisionStatus.DOWN


@pytest.mark.unit
def test_health_route_records_sidecar_status(runtime: LayaRuntime) -> None:
    runtime.install()
    runtime.start()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    set_process_runtime(runtime)
    from unittest.mock import patch

    import flinttrade_core.health_routes as health_routes

    report = type("Report", (), {})()
    report.overall_status = "healthy"
    from datetime import datetime, timedelta, timezone

    report.timestamp = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    with patch.object(health_routes.get_health_monitor(), "check_all", return_value=report):
        response = app.test_client().get("/health")
    assert response.status_code == 200
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    ping = app.test_client().get("/api/v1/ping").get_json()
    assert ping is not None
    assert ping["laya"] == "down"
    assert ping["laya_practice"] == "ready"
    assert ping["laya_live_qualified"] is False
    assert ping["laya_reason"] is None


@pytest.mark.unit
def test_failed_start_deletes_the_api_key(tmp_path: Path) -> None:
    def factory(_argv: list[str], _env: dict[str, str]) -> _Process:
        raise OSError("sidecar failed")

    runtime = LayaRuntime(tmp_path, process_factory=factory, artifact_checker=_unchecked_ready)
    root = runtime.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "verification.json").write_text('{"ok": true}', encoding="utf-8")
    (root / "run.json").write_text('{"token": "earlier", "pid": 1}', encoding="utf-8")
    with pytest.raises(OSError, match="sidecar failed"):
        runtime.start()
    assert not (root / "api.key").exists()
    assert not (root / "verification.json").exists()
    assert not (root / "run.json").exists()
    assert process_laya()._decision_client is None  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_two_venvs_sharing_one_base_interpreter_can_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    flint = tmp_path / "flint"
    sidecar = tmp_path / "sidecar"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(flint)], check=True)
    flint_python = venv_python(flint)
    side_python = venv_python(sidecar)
    pip_calls: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(argv: list[str], check: bool = False, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        args = [str(part) for part in argv]
        if "pip" in args:
            pip_calls.append(args)
            return subprocess.CompletedProcess(args, 0)
        if args[1:3] == ["-m", "venv"]:
            # This image has no ensurepip. A prefix-only environment still
            # shares the base interpreter symlink the guard used to follow.
            without = [args[0], "-m", "venv", "--without-pip", args[-1]]
            return real_run(without, check=check)  # type: ignore[arg-type]
        return real_run(argv, check=check, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("flinttrade_core.laya_runtime.subprocess.run", fake_run)
    monkeypatch.setattr(sys, "prefix", str(flint.resolve()))
    from flinttrade_core import laya_runtime as runtime_module

    runtime_module._default_install(sidecar, install_commands(sidecar))  # noqa: SLF001
    assert side_python.resolve() == flint_python.resolve()
    assert CPU_TORCH_INDEX in pip_calls[0]
    assert pip_calls[0][-1] == "torch"
    assert pip_calls[1][-1] == LAYA_SERVE_REQUIREMENT
    with pytest.raises(LayaRuntimeError, match="FlintTrade interpreter"):
        runtime_module._default_install(sidecar, [[str(flint_python), "-m", "pip", "install", "torch"]])  # noqa: SLF001


@pytest.mark.unit
def test_rocm_install_needs_an_https_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAYA_TORCH_INDEX", raising=False)
    with pytest.raises(LayaRuntimeError, match="LAYA_TORCH_INDEX"):
        install_commands(tmp_path / "venv", accelerator="rocm")
    monkeypatch.setenv("LAYA_TORCH_INDEX", "https://download.pytorch.org/whl/rocm6.3")
    commands = install_commands(tmp_path / "venv", accelerator="rocm")
    assert "https://download.pytorch.org/whl/rocm6.3" in commands[0]
    assert CPU_TORCH_INDEX not in commands[0]
    assert all(str(sidecar_constraints_path()) not in part for command in commands for part in command)


@pytest.mark.unit
def test_status_command_reports_the_loopback_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    assert main(["status"]) == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["running"] is False
    assert payload["host"] == "127.0.0.1"
    assert payload["port"] == 8000
    assert payload["base_url"] == "http://127.0.0.1:8000"
    assert payload["venv"].endswith("runtime/laya/venv")
    assert "api.key" not in captured
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_attach_uses_the_policy_pin_and_fails_closed_without_a_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "empty-hub"))
    key_path = tmp_path / "runtime" / "laya" / "api.key"
    key_path.parent.mkdir(parents=True)
    key_path.write_text("sidecar-key\n", encoding="utf-8")
    monkeypatch.setenv("LAYA_API_KEY_FILE", str(key_path))
    monkeypatch.setenv("LAYA_HOST", "127.0.0.1")
    monkeypatch.setenv("LAYA_PORT", "8000")
    runtime = attach_from_environment(tmp_path)
    assert runtime is not None
    client = process_laya()._decision_client  # noqa: SLF001
    assert client is not None
    assert client._expected_revision == load_policy().revision  # noqa: SLF001
    assert client._expected_sha256 == load_policy().sha256  # noqa: SLF001
    runtime._health_reader = lambda _url: _healthy()  # type: ignore[method-assign]
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    assert process_laya().runtime_reason()[0] is None
    missing = _healthy()
    missing.pop("sha256")
    runtime._health_reader = lambda _url: missing  # type: ignore[method-assign]
    runtime._artifact_checker = lambda: ArtifactCheck(  # type: ignore[method-assign]
        ok=False,
        reason="unverified",
        revision=load_policy().revision,
        sha256="",
    )
    runtime._artifact_check = None  # type: ignore[attr-defined]
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", 8000) == "Can't verify the model"
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_attach_refuses_a_public_host_and_a_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAYA_API_KEY_FILE", str(tmp_path / "missing.key"))
    monkeypatch.setenv("LAYA_HOST", "0.0.0.0")
    with pytest.raises(LayaRuntimeError, match="127.0.0.1"):
        attach_from_environment(tmp_path)
    monkeypatch.setenv("LAYA_HOST", "127.0.0.1")
    process_laya().set_status(DecisionStatus.READY)
    assert attach_from_environment(tmp_path) is None
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya()._decision_client is None  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_laya_port_selects_the_loopback_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAYA_PORT", raising=False)
    assert LayaRuntime(tmp_path).base_url == "http://127.0.0.1:8000"
    monkeypatch.setenv("LAYA_PORT", "8123")
    envs: list[dict[str, str]] = []

    def factory(_argv: list[str], env: dict[str, str]) -> _Process:
        envs.append(dict(env))
        return _Process()

    runtime = LayaRuntime(tmp_path, process_factory=factory, artifact_checker=_unchecked_ready)
    assert runtime.base_url == "http://127.0.0.1:8123"
    runtime.start()
    assert envs[-1]["LAYA_HOST"] == LAYA_BIND_HOST
    assert envs[-1]["LAYA_PORT"] == "8123"
    explicit = LayaRuntime(tmp_path, port=9000)
    assert explicit.base_url == "http://127.0.0.1:9000"
    monkeypatch.setenv("LAYA_PORT", "nope")
    with pytest.raises(LayaRuntimeError, match="invalid"):
        LayaRuntime(tmp_path)
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_status_reports_a_port_clash_as_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((LAYA_BIND_HOST, 0))
    sock.listen(1)
    port = int(sock.getsockname()[1])
    monkeypatch.setenv("LAYA_PORT", str(port))
    try:
        runtime = LayaRuntime(tmp_path, health_reader=lambda _url: None)
        report = runtime.status()
    finally:
        sock.close()
    assert report["running"] is False
    assert report["host"] == LAYA_BIND_HOST
    assert report["port"] == port
    assert report["reason"] == "port_in_use"
    assert report["detail"] == f"Port {port} in use"
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason() == ("port_in_use", port)
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_first_load_stays_down_for_admission_and_reports_still_loading(tmp_path: Path) -> None:
    payload: dict[str, object] | None = None

    def reader(_url: str) -> dict[str, object] | None:
        return payload

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        health_reader=reader,
        port_probe=lambda _port: False,
        artifact_checker=_unchecked_ready,
    )
    runtime.start()
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "still_loading"
    verdict = process_laya().admit(
        Proposal(symbol="RELIANCE", exchange="NSE", action="BUY", quantity=1, mode="practice", rationale="because")
    )
    assert verdict.allow is False
    assert verdict.reason == "Laya is Down. Orders are paused until it's Ready."
    assert "Live" not in verdict.reason
    payload = _healthy()
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    assert process_laya().runtime_reason()[0] is None
    payload = None
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unreachable"
    later = process_laya().admit(
        Proposal(symbol="RELIANCE", exchange="NSE", action="BUY", quantity=1, mode="practice", rationale="because")
    )
    assert later.allow is False
    assert later.reason == "Laya is Down. Orders are paused until it's Ready."
    runtime.stop()
    reset_process_laya_for_tests()


class _CountingProcess(_Process):
    def __init__(self) -> None:
        super().__init__()
        self.polls = 0

    def poll(self) -> int | None:
        self.polls += 1
        return super().poll()


@pytest.mark.unit
def test_health_probe_reaps_a_dead_child_and_reports_stopped(tmp_path: Path) -> None:
    process = _CountingProcess()
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: process,
        health_reader=lambda _url: None,
        port_probe=lambda _port: False,
        artifact_checker=_unchecked_ready,
    )
    runtime.start()
    process.returncode = 9
    set_process_runtime(runtime)
    from flinttrade_core.laya_runtime import refresh_process_laya_status

    refresh_process_laya_status()
    assert process.polls >= 1
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "stopped"
    reported = runtime.status()
    assert reported["running"] is False
    assert reported["detail"] == "Stopped"
    assert reported["reason"] == "stopped"
    runtime.stop()
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_health_probe_reaps_a_zombie_pid_that_kill_still_sees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LayaRuntime(
        tmp_path,
        port=8124,
        health_reader=lambda _url: None,
        port_probe=lambda _port: False,
    )
    runtime.runtime_root.mkdir(parents=True)
    (runtime.runtime_root / "sidecar.pid").write_text("424242")
    waited = {"n": 0}
    real_kill = os.kill

    def waitpid(pid: int, flags: int) -> tuple[int, int]:
        assert pid == 424242
        assert flags == os.WNOHANG
        waited["n"] += 1
        if waited["n"] == 1:
            return pid, 0
        raise ChildProcessError

    def kill(pid: int, sig: int) -> None:
        if pid == 424242:
            if waited["n"] == 0:
                return None
            raise ProcessLookupError
        real_kill(pid, sig)

    monkeypatch.setattr(os, "waitpid", waitpid)
    monkeypatch.setattr(os, "kill", kill)
    set_process_runtime(runtime)
    from flinttrade_core.laya_runtime import refresh_process_laya_status

    refresh_process_laya_status()
    assert waited["n"] >= 1
    assert process_laya().status is DecisionStatus.DOWN
    reason, port = process_laya().runtime_reason()
    assert reason == "stopped"
    assert port == 8124
    assert runtime.status()["detail"] == "Stopped"
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_exit_reaper_collects_a_dead_child_and_leaves_a_live_one(tmp_path: Path) -> None:
    dead = _CountingProcess()
    live = _CountingProcess()
    dead_runtime = LayaRuntime(
        tmp_path / "dead",
        process_factory=lambda _argv, _env: dead,
        health_reader=lambda _url: None,
        port_probe=lambda _port: False,
        artifact_checker=_unchecked_ready,
    )
    live_runtime = LayaRuntime(
        tmp_path / "live",
        port=8125,
        process_factory=lambda _argv, _env: live,
        health_reader=lambda _url: None,
        port_probe=lambda _port: False,
        artifact_checker=_unchecked_ready,
    )
    dead_runtime.start()
    live_runtime.start()
    dead.returncode = 1
    from flinttrade_core.laya_runtime import reap_managed_children

    reap_managed_children()
    assert dead.polls >= 1
    assert live.terminated is False
    assert live.returncode is None
    dead_runtime.stop()
    live_runtime.stop()
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_laya_start_is_operator_only_and_does_not_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    from flinttrade_core.auth_routes import _create_token

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    client = app.test_client()
    missing = client.post("/api/v1/laya/start")
    assert missing.status_code == 401

    def fail() -> str:
        raise LayaRuntimeError("venv missing under a private path")

    monkeypatch.setattr("flinttrade_core.laya_runtime.start_managed_sidecar", fail)
    token = _create_token("operator", mode="practice")
    headers = {"Authorization": f"Bearer {token}"}
    failed = client.post("/api/v1/laya/start", headers=headers)
    assert failed.status_code == 503
    assert failed.get_json()["message"] == "Laya could not be started."
    assert "private path" not in failed.get_data(as_text=True)

    calls: list[str] = []

    def started() -> str:
        calls.append("start")
        return "http://127.0.0.1:8000"

    monkeypatch.setattr("flinttrade_core.laya_runtime.start_managed_sidecar", started)
    ok = client.post("/api/v1/laya/start", headers=headers)
    assert ok.status_code == 200
    assert ok.get_json()["status"] == "ok"
    assert calls == ["start"]


def _accept_only(monkeypatch: pytest.MonkeyPatch, pid: int) -> None:
    monkeypatch.setattr("flinttrade_core.laya_runtime._pid_alive", lambda candidate: candidate == pid)


def _write_run(runtime: LayaRuntime, *, pid: int, token: str) -> None:
    policy = load_policy()
    root = runtime.runtime_root
    root.mkdir(parents=True, exist_ok=True)
    (root / "sidecar.pid").write_text(str(pid), encoding="utf-8")
    (root / "run.json").write_text(json.dumps({"token": token, "pid": pid}), encoding="utf-8")
    (root / "verification.json").write_text(
        json.dumps(
            {
                "ok": True,
                "reason": None,
                "revision": policy.revision,
                "sha256": policy.sha256,
                "pid": pid,
                "token": token,
            }
        ),
        encoding="utf-8",
    )


def _attached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checker: ArtifactCheck) -> LayaRuntime:
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "empty-hub"))
    key_path = tmp_path / "api.key"
    key_path.write_text("old-key\n", encoding="utf-8")
    monkeypatch.setenv("LAYA_API_KEY_FILE", str(key_path))
    monkeypatch.setenv("LAYA_HOST", "127.0.0.1")
    runtime = LayaRuntime(tmp_path, artifact_checker=lambda: checker)
    runtime.attach(key_path)
    return runtime


@pytest.mark.unit
def test_constraints_parser_rejects_an_extra() -> None:
    assert constraint_lines_with_extras("laya[serve]==0.3.21\n") == ["laya[serve]==0.3.21"]
    assert constraint_lines_with_extras("# laya[serve]==0.3.21\nlaya==0.3.21\n") == []


@pytest.mark.unit
def test_unpatched_health_is_ready_after_the_weight_file_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    live = 424242
    _accept_only(monkeypatch, live)
    payload = _healthy()
    payload.pop("sha256")
    runtime = _attached(
        tmp_path,
        monkeypatch,
        ArtifactCheck(ok=True, reason=None, revision=policy.revision, sha256=policy.sha256),
    )
    _write_run(runtime, pid=live, token="this-run")
    runtime._artifact_check = None  # noqa: SLF001
    runtime._health_reader = lambda _url: payload  # type: ignore[method-assign]
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    assert process_laya().runtime_reason()[0] is None
    client = process_laya()._decision_client  # noqa: SLF001
    assert client is not None
    assert client._verified == (policy.revision, policy.sha256)  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_leftover_verification_from_an_earlier_run_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = 424242
    _accept_only(monkeypatch, live)
    policy = load_policy()
    runtime = _attached(
        tmp_path,
        monkeypatch,
        ArtifactCheck(ok=True, reason=None, revision=policy.revision, sha256=policy.sha256),
    )
    _write_run(runtime, pid=111111, token="earlier-run")
    (runtime.runtime_root / "sidecar.pid").write_text(str(live), encoding="utf-8")
    runtime._artifact_check = None  # noqa: SLF001
    payload = _healthy()
    payload.pop("sha256")
    runtime._health_reader = lambda _url: payload  # type: ignore[method-assign]
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", 8000) == "Can't verify the model"
    assert laya_reason_tooltip("unverified", 8000) == (
        "The installed model couldn't be checked against the pinned version. "
        "Restart Laya. If it keeps happening, reinstall it."
    )
    client = process_laya()._decision_client  # noqa: SLF001
    assert client is not None
    assert client._verified is None  # noqa: SLF001
    _write_run(runtime, pid=live, token="this-run")
    recorded = json.loads((runtime.runtime_root / "verification.json").read_text(encoding="utf-8"))
    recorded["token"] = "earlier-run"
    (runtime.runtime_root / "verification.json").write_text(json.dumps(recorded), encoding="utf-8")
    runtime._artifact_check = None  # noqa: SLF001
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert client._verified is None  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_start_recomputes_the_weight_file_and_drops_it_on_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = 424242
    _accept_only(monkeypatch, live)
    policy = load_policy()
    calls = {"n": 0}

    def checker() -> ArtifactCheck:
        calls["n"] += 1
        return ArtifactCheck(ok=True, reason=None, revision=policy.revision, sha256=policy.sha256)

    class _LiveProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.pid = live

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _LiveProcess(),
        artifact_checker=checker,
        health_reader=lambda _url: _healthy(),
    )
    _write_run(runtime, pid=111111, token="earlier-run")
    runtime.start()
    assert calls["n"] == 1
    recorded = json.loads((runtime.runtime_root / "verification.json").read_text(encoding="utf-8"))
    run = json.loads((runtime.runtime_root / "run.json").read_text(encoding="utf-8"))
    assert recorded["token"] == run["token"]
    assert recorded["token"] != "earlier-run"
    assert recorded["pid"] == live
    assert recorded["sha256"] == policy.sha256
    payload = _healthy()
    payload.pop("sha256")
    runtime._health_reader = lambda _url: payload  # type: ignore[method-assign]
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    runtime.stop()
    assert not (runtime.runtime_root / "verification.json").exists()
    assert not (runtime.runtime_root / "run.json").exists()
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_weight_digest_mismatch_is_wrong_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_policy()
    path = tmp_path / "model.safetensors"
    path.write_bytes(b"not-the-pinned-weights")
    check = verify_weight_file(
        path,
        revision=policy.revision,
        expected_revision=policy.revision,
        expected_sha256=policy.sha256,
    )
    assert check.ok is False
    assert check.reason == "wrong_revision"
    live = 424242
    _accept_only(monkeypatch, live)

    class _LiveProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.pid = live

    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _LiveProcess(),
        artifact_checker=lambda: check,
        health_reader=lambda _url: _healthy(),
    )
    with pytest.raises(LayaRuntimeError, match="Wrong model version"):
        runtime.start()
    assert launched == []
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "wrong_revision"
    assert laya_reason_detail("wrong_revision", 8000) == "Wrong model version"
    assert laya_reason_tooltip("wrong_revision", 8000) == (
        "Laya is running a different model than FlintTrade expects."
    )
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_stale_api_key_is_reread_and_a_rejected_key_stays_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    runtime = _attached(
        tmp_path,
        monkeypatch,
        ArtifactCheck(ok=True, reason=None, revision=policy.revision, sha256=policy.sha256),
    )
    runtime._health_reader = lambda _url: _healthy()  # type: ignore[method-assign]
    key_path = tmp_path / "api.key"
    key_path.write_text("fresh-key\n", encoding="utf-8")
    runtime.publish_status()
    client = process_laya()._decision_client  # noqa: SLF001
    assert client is not None
    assert client._api_key == "fresh-key"  # noqa: SLF001
    assert process_laya().effective_status("practice") is DecisionStatus.READY

    runtime._mark_key_rejected()
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "key_rejected"
    assert laya_reason_detail("key_rejected", runtime._port) == "Can't reach Laya"  # noqa: SLF001
    assert laya_reason_tooltip("key_rejected", runtime._port) == (  # noqa: SLF001
        "Laya restarted with a new key. Reconnecting…"
    )
    assert process_laya().effective_status("practice") is not DecisionStatus.READY

    key_path.write_text("rotated-key\n", encoding="utf-8")
    runtime.publish_status()
    assert client._api_key == "rotated-key"  # noqa: SLF001
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    reset_process_laya_for_tests()


def _plant_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, extra: str | None) -> Path:
    policy = load_policy()
    root = tmp_path / "hub"
    path = snapshot_weight_path(
        root,
        repo=policy.repo,
        revision=policy.revision,
        filename=policy.weight_file,
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"pinned-weights")
    for name, _digest in policy.manifest:
        companion = path.parent / name
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_bytes(b"companion:" + name.encode())
    (path.parent / "README.md").write_bytes(b"not-loaded")
    if extra is not None:
        extra_path = path.parent / extra
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_bytes(b"not-the-pinned-file")
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(root))
    return path


def _accept_pinned_digests(monkeypatch: pytest.MonkeyPatch, policy: Any, *, wrong: str | None = None) -> None:
    """Return the pinned digest for each snapshot file. ``wrong`` is a mismatch."""
    pins = [(policy.weight_file, policy.sha256), *policy.manifest]

    def fake(path: Path) -> str:
        text = path.as_posix()
        for name, digest in sorted(pins, key=lambda item: len(item[0]), reverse=True):
            if text.endswith("/" + name):
                if name == wrong:
                    return "0" * 64
                return digest
        raise AssertionError(text)

    monkeypatch.setattr("flinttrade_core.laya_runtime.sha256_file", fake)


@pytest.mark.unit
@pytest.mark.parametrize(
    "extra",
    ["model.safetensors.index.json", "pytorch_model.bin.index.json", "other.safetensors", "weights.bin", "model.pt", "model.pth", "model.gguf"],
)
def test_extra_snapshot_weights_are_unverified_and_do_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    path = _plant_snapshot(tmp_path, monkeypatch, extra=extra)
    policy = load_policy()
    check = verify_installed_model(
        repo=policy.repo,
        revision=policy.revision,
        filename=policy.weight_file,
        expected_sha256=policy.sha256,
    )
    assert check.ok is False
    assert check.reason == "unverified"
    assert check.weights_path
    direct = verify_weight_file(
        path,
        revision=policy.revision,
        expected_revision=policy.revision,
        expected_sha256=policy.sha256,
    )
    assert direct.reason == "unverified"
    assert find_pinned_weight(repo=policy.repo, revision=policy.revision, filename=policy.weight_file) is None
    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't verify the model"):
        runtime.start()
    assert launched == []
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", runtime._port) == "Can't verify the model"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_tampered_weight_is_wrong_revision_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant_snapshot(tmp_path, monkeypatch, extra=None)
    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Wrong model version"):
        runtime.start()
    assert launched == []
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "wrong_revision"
    assert laya_reason_detail("wrong_revision", runtime._port) == "Wrong model version"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_clean_weight_is_logged_and_launched_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    policy = load_policy()
    path = _plant_snapshot(tmp_path, monkeypatch, extra=None)
    _accept_pinned_digests(monkeypatch, policy)
    launched: list[tuple[list[str], dict[str, str]]] = []

    def factory(argv: list[str], env: dict[str, str]) -> _Process:
        launched.append((argv, env))
        return _Process()

    runtime = LayaRuntime(
        tmp_path,
        process_factory=factory,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with caplog.at_level(logging.INFO, logger="flinttrade.laya"):
        runtime.start()
    assert launched
    argv, env = launched[0]
    resolved = str(path.resolve())
    assert not (runtime.runtime_root / "launch").exists()
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["LAYA_WEIGHTS_PATH"] == resolved
    digests = json.loads(env["LAYA_SHA256_DIGESTS"])
    assert digests[policy.weight_file] == policy.sha256
    assert dict(policy.manifest).items() <= digests.items()
    assert "LAYA_REVISION" not in env
    assert "LAYA_MODELS" not in env
    assert policy.repo not in env.values()
    assert policy.revision not in env.values()
    child = "\n".join(argv)
    assert "LAYA_WEIGHTS_PATH" in child
    assert "HF_HUB_OFFLINE" in child
    assert "TRANSFORMERS_OFFLINE" in child
    assert policy.repo not in child
    assert policy.revision not in child
    expected = LAYA_WEIGHTS_LOG % (resolved, policy.sha256)
    assert expected in caplog.text
    recorded = json.loads((runtime.runtime_root / "verification.json").read_text(encoding="utf-8"))
    stat = path.stat()
    assert recorded["weights_path"] == resolved
    assert "launch_path" not in recorded
    assert recorded["sha256"] == policy.sha256
    assert recorded["inode"] == stat.st_ino
    assert recorded["size"] == stat.st_size
    assert recorded["mtime_ns"] == stat.st_mtime_ns
    for name, digest in policy.manifest:
        source = path.parent / name
        source_stat = source.stat()
        remembered = next(item for item in recorded["files"] if item["path"] == str(source))
        assert remembered["name"] == name
        assert remembered["sha256"] == digest
        assert remembered["inode"] == source_stat.st_ino
        assert remembered["size"] == source_stat.st_size
        assert remembered["mtime_ns"] == source_stat.st_mtime_ns
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_pid_and_key_changes_flip_status_within_the_watch_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert 1 <= LAYA_WATCH_INTERVAL_SECONDS <= 2
    live = 424242
    _accept_only(monkeypatch, live)
    policy = load_policy()
    key_path = tmp_path / "api.key"
    key_path.write_text("old-key\n", encoding="utf-8")
    runtime = LayaRuntime(
        tmp_path,
        watch=True,
        watch_interval=0.05,
        artifact_checker=lambda: ArtifactCheck(
            ok=True, reason=None, revision=policy.revision, sha256=policy.sha256
        ),
        health_reader=lambda _url: _healthy(),
    )
    runtime.attach(key_path)
    (runtime.runtime_root / "sidecar.pid").write_text(str(live), encoding="utf-8")
    runtime._watch_had_pid = True  # noqa: SLF001
    deadline = time.monotonic() + 1
    client = process_laya()._decision_client  # noqa: SLF001
    assert client is not None
    key_path.write_text("rotated-key\n", encoding="utf-8")
    while time.monotonic() < deadline and client._api_key != "rotated-key":  # noqa: SLF001
        time.sleep(0.02)
    assert client._api_key == "rotated-key"  # noqa: SLF001
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    (runtime.runtime_root / "sidecar.pid").unlink()
    while time.monotonic() < deadline and process_laya().runtime_reason()[0] != "stopped":
        time.sleep(0.02)
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "stopped"
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    runtime.stop_watch()
    reset_process_laya_for_tests()


def _shift_weight_identity(path: Path, field: str) -> None:
    """Change one of inode, size, or mtime without touching the other two."""
    before = path.stat()
    if field == "mtime":
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
        return
    if field == "size":
        path.write_bytes(path.read_bytes() + b"x")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return
    replacement = path.with_name(path.name + ".swap")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


@pytest.mark.unit
@pytest.mark.parametrize("field", ["mtime", "size", "inode"])
@pytest.mark.parametrize("when", ["ready", "watch"])
def test_weight_identity_drift_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    field: str,
    when: str,
) -> None:
    live = 424242
    _accept_only(monkeypatch, live)
    policy = load_policy()
    path = _plant_snapshot(tmp_path, monkeypatch, extra=None)
    _accept_pinned_digests(monkeypatch, policy)

    class _LiveProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.pid = live

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _LiveProcess(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime.start()

    def hashed_again(_path: Path) -> str:
        raise AssertionError("re-hash")

    monkeypatch.setattr("flinttrade_core.laya_runtime.sha256_file", hashed_again)
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    _shift_weight_identity(path, field)
    with caplog.at_level(logging.INFO, logger="flinttrade.laya"):
        if when == "ready":
            runtime.publish_status()
        else:
            runtime.reconcile_watched_state()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", runtime._port) == "Can't verify the model"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    stat = path.stat()
    recorded = json.loads((runtime.runtime_root / "verification.json").read_text(encoding="utf-8"))
    changed: list[str] = []
    if stat.st_ino != recorded["inode"]:
        changed.append("inode")
    if stat.st_size != recorded["size"]:
        changed.append("size")
    if stat.st_mtime_ns != recorded["mtime_ns"]:
        changed.append("mtime")
    assert field in changed
    assert LAYA_WEIGHTS_DRIFT_LOG % (recorded["weights_path"], ",".join(changed)) in caplog.text
    reset_process_laya_for_tests()


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    ["encoder/config.json", "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json"],
)
def test_changed_companion_is_wrong_revision_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    _plant_snapshot(tmp_path, monkeypatch, extra=None)
    policy = load_policy()
    _accept_pinned_digests(monkeypatch, policy, wrong=name)
    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Wrong model version"):
        runtime.start()
    assert launched == []
    refusal = runtime._launch_refusal  # noqa: SLF001
    assert refusal is not None
    assert refusal.reason == "wrong_revision"
    assert refusal.weights_path.endswith(name)
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "wrong_revision"
    assert laya_reason_detail("wrong_revision", runtime._port) == "Wrong model version"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    reset_process_laya_for_tests()


@pytest.mark.unit
@pytest.mark.parametrize("name", ["encoder/config.json", "tokenizer/tokenizer.json"])
def test_missing_companion_is_unverified_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    path = _plant_snapshot(tmp_path, monkeypatch, extra=None)
    (path.parent / name).unlink()
    policy = load_policy()
    _accept_pinned_digests(monkeypatch, policy)
    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't verify the model"):
        runtime.start()
    assert launched == []
    refusal = runtime._launch_refusal  # noqa: SLF001
    assert refusal is not None
    assert refusal.reason == "unverified"
    assert refusal.weights_path.endswith(name)
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", runtime._port) == "Can't verify the model"  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
@pytest.mark.parametrize("extra", ["config.json", "tokenizer/added_tokens.json"])
def test_extra_loadable_file_is_unverified_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str
) -> None:
    _plant_snapshot(tmp_path, monkeypatch, extra=extra)
    launched: list[object] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't verify the model"):
        runtime.start()
    assert launched == []
    refusal = runtime._launch_refusal  # noqa: SLF001
    assert refusal is not None
    assert refusal.reason == "unverified"
    assert refusal.weights_path.endswith(extra)
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", runtime._port) == "Can't verify the model"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    reset_process_laya_for_tests()


@pytest.mark.unit
@pytest.mark.parametrize("name", ["encoder/config.json", "tokenizer/tokenizer.json"])
@pytest.mark.parametrize("when", ["ready", "watch"])
def test_companion_identity_drift_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    name: str,
    when: str,
) -> None:
    live = 424242
    _accept_only(monkeypatch, live)
    policy = load_policy()
    path = _plant_snapshot(tmp_path, monkeypatch, extra=None)
    _accept_pinned_digests(monkeypatch, policy)

    class _LiveProcess(_Process):
        def __init__(self) -> None:
            super().__init__()
            self.pid = live

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _LiveProcess(),
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime.start()

    def hashed_again(_path: Path) -> str:
        raise AssertionError("re-hash")

    monkeypatch.setattr("flinttrade_core.laya_runtime.sha256_file", hashed_again)
    runtime.publish_status()
    assert process_laya().effective_status("practice") is DecisionStatus.READY
    companion = path.parent / name
    before = companion.stat()
    os.utime(companion, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
    with caplog.at_level(logging.INFO, logger="flinttrade.laya"):
        if when == "ready":
            runtime.publish_status()
        else:
            runtime.reconcile_watched_state()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "unverified"
    assert laya_reason_detail("unverified", runtime._port) == "Can't verify the model"  # noqa: SLF001
    assert process_laya().effective_status("practice") is not DecisionStatus.READY
    assert LAYA_WEIGHTS_DRIFT_LOG % (str(companion), "mtime") in caplog.text
    assert name in caplog.text
    reset_process_laya_for_tests()


def _write_pinned_snapshot(root: Path) -> Path:
    """Write the pinned weights file and manifest into a hub cache. Does not set the environment."""
    policy = load_policy()
    path = snapshot_weight_path(
        root,
        repo=policy.repo,
        revision=policy.revision,
        filename=policy.weight_file,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"pinned-weights")
    for name, _digest in policy.manifest:
        companion = path.parent / name
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_bytes(b"companion:" + name.encode())
    return path


def _write_pinned_tree(directory: Path) -> Path:
    """Write the pinned weights file and manifest as a flat checkpoint directory."""
    policy = load_policy()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / policy.weight_file
    path.write_bytes(b"pinned-weights")
    for name, _digest in policy.manifest:
        companion = directory / name
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_bytes(b"companion:" + name.encode())
    return path


_PINNED_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"


@pytest.mark.unit
def test_clean_cache_downloads_then_launches_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    policy = load_policy()
    cache = tmp_path / "hub"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(cache))
    _accept_pinned_digests(monkeypatch, policy)
    order: list[str] = []
    launched: list[dict[str, str]] = []

    def download(argv: list[str], env: dict[str, str]) -> int:
        order.append("download")
        assert env["HF_HUB_OFFLINE"] == "0"
        assert env["LAYA_REPO"] == policy.repo
        assert env["LAYA_REVISION"] == policy.revision
        assert env["LAYA_REVISION"] == _PINNED_REVISION
        assert env["LAYA_REVISION"] != "main"
        assert "HUGGINGFACE_HUB_CACHE" not in env
        assert "LAYA_DOWNLOAD_DIR" in env
        staging = Path(env["LAYA_DOWNLOAD_DIR"])
        assert staging.name == "staging"
        assert staging != runtime_root_checkpoint(staging)
        assert "snapshot_download" in "\n".join(argv)
        assert "revision=revision" in "\n".join(argv)
        assert "laya-serve" not in "\n".join(argv)
        assert env.get("TRANSFORMERS_OFFLINE") != "1"
        assert "LAYA_WEIGHTS_PATH" not in env
        _write_pinned_tree(staging)
        return 0

    def factory(_argv: list[str], env: dict[str, str]) -> _Process:
        order.append("launch")
        launched.append(dict(env))
        return _Process()

    runtime = LayaRuntime(
        tmp_path,
        process_factory=factory,
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with caplog.at_level(logging.INFO, logger="flinttrade.laya"):
        runtime.start()
    assert order == ["download", "launch"]
    env = launched[0]
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["TRANSFORMERS_OFFLINE"] == "1"
    assert "LAYA_REVISION" not in env
    assert "LAYA_MODELS" not in env
    assert env["LAYA_WEIGHTS_PATH"].endswith(policy.weight_file)
    assert "checkpoint" in env["LAYA_WEIGHTS_PATH"]
    assert "staging" not in env["LAYA_WEIGHTS_PATH"]
    assert str(cache) not in env["LAYA_WEIGHTS_PATH"]
    assert not runtime.staging_dir.exists()
    assert (runtime.checkpoint_dir / policy.weight_file).is_file()
    assert not cache.exists() or not any(cache.rglob("*"))
    assert LAYA_DOWNLOAD_LOG % (policy.repo, policy.revision) in caplog.text
    assert policy.sha256 in caplog.text
    reset_process_laya_for_tests()


def runtime_root_checkpoint(staging: Path) -> Path:
    """Launch directory that sits next to a staging directory."""
    return staging.parent / "checkpoint"


@pytest.mark.unit
def test_tampered_download_is_removed_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    cache = tmp_path / "hub"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(cache))
    _accept_pinned_digests(monkeypatch, policy, wrong="encoder/config.json")
    repo = cache / ("models--" + policy.repo.replace("/", "--"))
    keeper = repo / "blobs" / "already-there"
    keeper.parent.mkdir(parents=True)
    keeper.write_bytes(b"keep")
    other = cache / "models--other--repo" / "config.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"leave-this")
    launched: list[object] = []

    def download(_argv: list[str], env: dict[str, str]) -> int:
        path = _write_pinned_tree(Path(env["LAYA_DOWNLOAD_DIR"]))
        (path.parent / "encoder" / "config.json").write_bytes(b"tampered")
        return 0

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Wrong model version"):
        runtime.start()
    assert launched == []
    assert runtime._process is None  # noqa: SLF001
    assert not (runtime.runtime_root / "sidecar.pid").exists()
    assert not runtime.staging_dir.exists()
    assert not (runtime.checkpoint_dir / policy.weight_file).exists()
    assert keeper.read_bytes() == b"keep"
    assert other.read_bytes() == b"leave-this"
    assert not any(cache.rglob("model.safetensors"))
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "wrong_revision"
    assert laya_reason_detail("wrong_revision", runtime._port) == "Wrong model version"  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_failed_download_does_not_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_policy()
    cache = tmp_path / "hub"
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(cache))
    repo = cache / ("models--" + policy.repo.replace("/", "--"))
    launched: list[object] = []

    keeper = repo / "blobs" / "already-there"
    keeper.parent.mkdir(parents=True)
    keeper.write_bytes(b"keep")

    def download(_argv: list[str], env: dict[str, str]) -> int:
        partial = Path(env["LAYA_DOWNLOAD_DIR"]) / policy.weight_file
        partial.write_bytes(b"partial")
        return 1

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't download the model"):
        runtime.start()
    assert launched == []
    assert not (runtime.runtime_root / "sidecar.pid").exists()
    assert not runtime.staging_dir.exists()
    assert not (runtime.checkpoint_dir / policy.weight_file).exists()
    assert keeper.read_bytes() == b"keep"
    report = runtime.status()
    assert report["reason"] == "download_failed"
    assert report["detail"] == "Can't download the model"
    assert report["tooltip"] == "Check your connection, then Start Laya again."
    assert "Next:" not in str(report["tooltip"])
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "download_failed"
    assert laya_reason_detail("download_failed", runtime._port) == "Can't download the model"  # noqa: SLF001
    assert laya_reason_tooltip("download_failed", runtime._port) == (  # noqa: SLF001
        "Check your connection, then Start Laya again."
    )
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_download_uses_the_pinned_revision_not_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    seen: dict[str, str] = {}

    def download(argv: list[str], env: dict[str, str]) -> int:
        seen["revision"] = env["LAYA_REVISION"]
        seen["script"] = "\n".join(argv)
        return 1

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't download the model"):
        runtime.start()
    assert seen["revision"] == policy.revision
    assert seen["revision"] == _PINNED_REVISION
    assert seen["revision"] != "main"
    assert "revision=revision" in seen["script"]
    assert "revision=revision" in LAYA_DOWNLOAD_BOOTSTRAP
    assert '"main"' not in LAYA_DOWNLOAD_BOOTSTRAP
    assert "'main'" not in LAYA_DOWNLOAD_BOOTSTRAP
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_download_progress_updates_the_chip_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests(monkeypatch, policy)
    seen: list[str] = []

    def download(_argv: list[str], env: dict[str, str], progress: Any) -> int:
        progress(500_000_000, 3_400_000_000)
        first = process_laya().download_progress()
        assert first is not None
        seen.append(laya_reason_detail("downloading", 8000, progress=first) or "")
        progress(1_200_000_000, 3_400_000_000)
        second = process_laya().download_progress()
        assert second == (1_200_000_000, 3_400_000_000)
        seen.append(laya_reason_detail("downloading", 8000, progress=second) or "")
        assert process_laya().runtime_reason()[0] == "downloading"
        assert process_laya().status is DecisionStatus.DOWN
        assert laya_reason_tooltip("downloading", 8000) is None
        verdict = process_laya().admit(
            Proposal(symbol="RELIANCE", exchange="NSE", action="BUY", quantity=1, mode="practice")
        )
        assert verdict.reason == "Laya is Down. Orders are paused until it's Ready."
        _write_pinned_tree(Path(env["LAYA_DOWNLOAD_DIR"]))
        return 0

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime.start()
    assert seen == [
        "Downloading the model · 0.5 of 3.4 GB",
        "Downloading the model · 1.2 of 3.4 GB",
    ]
    reset_process_laya_for_tests()


def _write_old_tree(directory: Path) -> None:
    """Write a previous revision: same names, bytes that are not the pin."""
    policy = load_policy()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / policy.weight_file).write_bytes(b"old-weights")
    for name, _digest in policy.manifest:
        companion = directory / name
        companion.parent.mkdir(parents=True, exist_ok=True)
        companion.write_bytes(b"old-" + name.encode())
    (directory / "README.md").write_bytes(b"old-marker")


def _accept_pinned_digests_except_old(monkeypatch: pytest.MonkeyPatch, policy: Any) -> None:
    """Pinned digest for current bytes. A previous revision starts with ``old-``."""
    pins = [(policy.weight_file, policy.sha256), *policy.manifest]

    def fake(path: Path) -> str:
        if path.read_bytes().startswith(b"old-"):
            return "0" * 64
        text = path.as_posix()
        for name, digest in sorted(pins, key=lambda item: len(item[0]), reverse=True):
            if text.endswith("/" + name):
                return digest
        raise AssertionError(text)

    monkeypatch.setattr("flinttrade_core.laya_runtime.sha256_file", fake)


def _old_checkpoint_names(runtime: LayaRuntime) -> list[str]:
    return sorted(
        child.name
        for child in runtime.runtime_root.iterdir()
        if child.name.startswith("checkpoint.old-")
    )


@pytest.mark.unit
def test_pin_upgrade_replaces_the_checkpoint_and_removes_the_old_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests_except_old(monkeypatch, policy)
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        downloader=lambda _argv, env: _write_pinned_tree(Path(env["LAYA_DOWNLOAD_DIR"])) and 0,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime._ensure_dirs()  # noqa: SLF001
    _write_old_tree(runtime.checkpoint_dir)
    launched: list[dict[str, str]] = []

    def factory(_argv: list[str], env: dict[str, str]) -> _Process:
        launched.append(dict(env))
        return _Process()

    runtime._process_factory = factory  # noqa: SLF001
    runtime.start()
    assert launched
    assert launched[0]["HF_HUB_OFFLINE"] == "1"
    assert "checkpoint" in launched[0]["LAYA_WEIGHTS_PATH"]
    assert (runtime.checkpoint_dir / policy.weight_file).read_bytes() == b"pinned-weights"
    assert not (runtime.checkpoint_dir / "README.md").exists()
    assert _old_checkpoint_names(runtime) == []
    assert not runtime.staging_dir.exists()
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_failed_upgrade_rename_restores_the_old_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests_except_old(monkeypatch, policy)
    launched: list[object] = []
    real_replace = os.replace

    def flaky(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        if Path(src).name == "staging" and Path(dst).name == "checkpoint":
            raise OSError("second rename failed")
        real_replace(src, dst)

    monkeypatch.setattr("flinttrade_core.laya_runtime.os.replace", flaky)

    def download(_argv: list[str], env: dict[str, str]) -> int:
        _write_pinned_tree(Path(env["LAYA_DOWNLOAD_DIR"]))
        return 0

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime._ensure_dirs()  # noqa: SLF001
    _write_old_tree(runtime.checkpoint_dir)
    with pytest.raises(LayaRuntimeError, match="Can't download the model"):
        runtime.start()
    assert launched == []
    assert runtime._process is None  # noqa: SLF001
    assert (runtime.checkpoint_dir / "README.md").read_bytes() == b"old-marker"
    assert (runtime.checkpoint_dir / policy.weight_file).read_bytes() == b"old-weights"
    assert _old_checkpoint_names(runtime) == []
    assert not runtime.staging_dir.exists()
    report = runtime.status()
    assert report["reason"] == "download_failed"
    assert report["detail"] == "Can't download the model"
    assert report["tooltip"] == "Check your connection, then Start Laya again."
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "download_failed"
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_failed_upgrade_download_reports_download_failed_not_wrong_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests_except_old(monkeypatch, policy)
    launched: list[object] = []

    def download(_argv: list[str], env: dict[str, str]) -> int:
        partial = Path(env["LAYA_DOWNLOAD_DIR"]) / policy.weight_file
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial")
        return 1

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime._ensure_dirs()  # noqa: SLF001
    _write_old_tree(runtime.checkpoint_dir)
    with pytest.raises(LayaRuntimeError, match="Can't download the model"):
        runtime.start()
    assert launched == []
    assert (runtime.checkpoint_dir / "README.md").read_bytes() == b"old-marker"
    assert not runtime.staging_dir.exists()
    assert process_laya().runtime_reason()[0] == "download_failed"
    assert laya_reason_detail("download_failed", runtime._port) == "Can't download the model"  # noqa: SLF001
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_failed_download_with_old_snapshot_is_download_failed_not_wrong_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    path = _plant_snapshot(tmp_path, monkeypatch, extra=None)
    (path.parent / "encoder" / "config.json").unlink()
    launched: list[object] = []

    def download(_argv: list[str], env: dict[str, str]) -> int:
        partial = Path(env["LAYA_DOWNLOAD_DIR"]) / policy.weight_file
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial")
        return 1

    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: launched.append(1) or _Process(),
        downloader=download,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    with pytest.raises(LayaRuntimeError, match="Can't download the model"):
        runtime.start()
    assert launched == []
    assert runtime._process is None  # noqa: SLF001
    assert path.is_file()
    assert not runtime.staging_dir.exists()
    report = runtime.status()
    assert report["reason"] == "download_failed"
    assert report["detail"] == "Can't download the model"
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "download_failed"
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_stale_staging_and_old_checkpoint_are_removed_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests(monkeypatch, policy)
    calls: list[str] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        downloader=lambda *_args: calls.append("download") or 1,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime._ensure_dirs()  # noqa: SLF001
    _write_pinned_tree(runtime.checkpoint_dir)
    stale = runtime.staging_dir / "partial"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale-staging")
    leftover = runtime.runtime_root / "checkpoint.old-stale"
    leftover.mkdir()
    (leftover / "README.md").write_bytes(b"leftover")
    with caplog.at_level(logging.INFO, logger="flinttrade.laya"):
        runtime.start()
    assert calls == []
    assert not runtime.staging_dir.exists()
    assert _old_checkpoint_names(runtime) == []
    assert (runtime.checkpoint_dir / policy.weight_file).is_file()
    assert "checkpoint.old" not in caplog.text
    assert process_laya().runtime_reason()[0] != "download_failed"
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_crash_between_renames_restores_the_old_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_policy()
    monkeypatch.setenv("HUGGINGFACE_HUB_CACHE", str(tmp_path / "hub"))
    _accept_pinned_digests(monkeypatch, policy)
    calls: list[str] = []
    runtime = LayaRuntime(
        tmp_path,
        process_factory=lambda _argv, _env: _Process(),
        downloader=lambda *_args: calls.append("download") or 1,
        health_reader=lambda _url: _healthy(),
        watch=False,
    )
    runtime._ensure_dirs()  # noqa: SLF001
    junk = runtime.runtime_root / "checkpoint.old-aaa"
    junk.mkdir()
    (junk / "README.md").write_bytes(b"junk")
    restored = runtime.runtime_root / "checkpoint.old-zzz"
    _write_pinned_tree(restored)
    assert not runtime.checkpoint_dir.exists()
    runtime.start()
    assert calls == []
    assert (runtime.checkpoint_dir / policy.weight_file).read_bytes() == b"pinned-weights"
    assert _old_checkpoint_names(runtime) == []
    assert not junk.exists()
    reset_process_laya_for_tests()
