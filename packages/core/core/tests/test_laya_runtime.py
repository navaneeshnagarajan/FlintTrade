"""Opt-in Laya sidecar: loopback, pinned package, and the status probe."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from flinttrade_core.health_routes import health_bp
from flinttrade_core.laya_runtime import (
    CPU_TORCH_INDEX,
    LAYA_BIND_HOST,
    LAYA_SERVE_REQUIREMENT,
    LayaRuntime,
    LayaRuntimeError,
    attach_from_environment,
    cpu_torch_command,
    install_command,
    install_commands,
    main,
    set_process_runtime,
    sidecar_constraints_path,
    venv_python,
)
from flinttrade_core.service_providers import EvidenceUseScope
from flinttrade_engine.laya import DecisionStatus, Proposal, process_laya, reset_process_laya_for_tests
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


@pytest.fixture
def runtime(tmp_path: Path) -> Any:
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
    assert "laya[serve]==0.3.21" in pinned
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
    assert env["LAYA_REVISION"] == load_policy().revision
    assert load_policy().sha256 in env["LAYA_SHA256_DIGESTS"]
    assert env["HF_HUB_OFFLINE"] == "0"
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

    runtime = LayaRuntime(tmp_path, process_factory=lambda _argv, _env: _Process(), health_reader=reader)
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

    runtime = LayaRuntime(tmp_path, process_factory=factory)
    with pytest.raises(OSError, match="sidecar failed"):
        runtime.start()
    assert not (runtime.runtime_root / "api.key").exists()
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
    runtime.publish_status()
    assert process_laya().status is DecisionStatus.DOWN
    assert process_laya().runtime_reason()[0] == "wrong_revision"
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

    runtime = LayaRuntime(tmp_path, process_factory=factory)
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
    reset_process_laya_for_tests()
