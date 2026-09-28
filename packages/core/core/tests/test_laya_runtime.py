"""Opt-in Laya sidecar: loopback, pinned package, and the status probe."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from flinttrade_core.health_routes import health_bp
from flinttrade_core.laya_runtime import (
    LAYA_SERVE_REQUIREMENT,
    LayaRuntime,
    LayaRuntimeError,
    install_command,
    set_process_runtime,
    venv_python,
)
from flinttrade_core.service_providers import EvidenceUseScope
from flinttrade_engine.laya import DecisionStatus, process_laya, reset_process_laya_for_tests
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
    assert LAYA_SERVE_REQUIREMENT in command
    assert command[0] == str(venv_python(venv))
    assert Path(command[0]) != Path(sys.executable)
    root = Path(__file__).resolve().parents[4]
    assert "laya" not in (root / "packages/core/core/pyproject.toml").read_text(encoding="utf-8")
    assert "unsloth" not in (root / "packages/core/core/src/flinttrade_core/laya_runtime.py").read_text(
        encoding="utf-8"
    )


@pytest.mark.unit
def test_start_binds_loopback_mints_a_key_and_pins_the_checkpoint(runtime: LayaRuntime) -> None:
    runtime.install()
    runtime.start()
    env = runtime.envs[-1]  # type: ignore[attr-defined]
    assert runtime.commands[-1][-1] == LAYA_SERVE_REQUIREMENT  # type: ignore[attr-defined]
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
    process = runtime.created[-1]  # type: ignore[attr-defined]
    runtime.stop()
    assert process.terminated is True
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
