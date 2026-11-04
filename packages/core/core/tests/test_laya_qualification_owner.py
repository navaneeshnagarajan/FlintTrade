"""Normal-factory qualification with inert HTTP and real runtime identity.

Synthetic checkpoint bytes and labelled protocol cases prove engineering
correspondence only. They do not qualify a model, broker or funded Live use.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


@pytest.fixture
def sidecar(
    mounted_desk: MountedDesk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Any, list[str]]]:
    """Start the actual runtime with a sterile child and inert HTTP bytes.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.

    Yields:
        Managed runtime and inert HTTP ledger until original runtime cleanup.
    """
    import urllib.request

    from flinttrade_core.laya_runtime import LayaRuntime
    from flinttrade_engine import laya_decision

    original_policy = laya_decision.load_policy()
    weights = b"synthetic engineering checkpoint, not a model"
    companion = b"{}"
    policy = replace(
        original_policy, revision="a" * 40, sha256=hashlib.sha256(weights).hexdigest(),
        manifest=(("config.json", hashlib.sha256(companion).hexdigest()),),
    )
    monkeypatch.setattr(laya_decision, "load_policy", lambda: policy)
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "sidecar")
    calls: list[str] = []

    class Response:
        """Bounded inert HTTP body, not a decision or qualification object."""

        status = 200

        def __init__(self, body: dict[str, Any]) -> None:
            self.body = json.dumps(body).encode()

        def read(self, count: int) -> bytes:
            """Return at most the client's requested byte bound."""
            return self.body[:count]

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def transport(request: Any, **_kwargs: Any) -> Response:
        url = request.full_url if isinstance(request, urllib.request.Request) else request
        calls.append(url)
        assert url.startswith("http://127.0.0.1:8000/")
        if url.endswith("/health"):
            return Response({"status": "ok", "loaded": [policy.checkpoint], "device": "cpu",
                             "revisions": {policy.checkpoint: policy.revision}, "sha256": policy.sha256})
        assert url.endswith("/v1/systemone") and request.method == "POST"
        body = json.loads(request.data)
        assert set(body["questions"]) == {"rationale", "tilt", "side"}
        deny = "revenge" in body["state"]
        return Response({"revision": policy.revision, "sha256": policy.sha256, "answers": {
            "rationale": {"probabilities": {"A": 1.0, "B": 0.0}},
            "tilt": {"probabilities": {"A": 1.0 if deny else 0.0, "B": 0.0 if deny else 1.0}},
            "side": {"probabilities": {"A": 0.0, "B": 1.0}},
        }})

    monkeypatch.setattr(urllib.request, "urlopen", transport)

    def spawn(_argv: list[str], _env: dict[str, str]) -> subprocess.Popen[bytes]:
        # Only the external process is inert. Runtime start, hashing, record,
        # pid/key custody and HTTP decision parsing are the real implementation.
        return subprocess.Popen([sys.executable, "-I", "-S", "-c", "import time;time.sleep(120)"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    runtime = LayaRuntime(tmp_path, process_factory=spawn, watch=False)
    runtime.checkpoint_dir.mkdir(parents=True)
    (runtime.checkpoint_dir / policy.weight_file).write_bytes(weights)
    (runtime.checkpoint_dir / "config.json").write_bytes(companion)
    try:
        runtime.start()
        yield runtime, calls
    finally:
        runtime.stop()


def test_factory_qualification_scores_runtime_and_retires_exact_owner(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]],
) -> None:
    """Missing evidence refuses; genuine checks admit; retirement denies again.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        sidecar: Actual managed sidecar runtime and its inert HTTP request ledger.
    """
    from flinttrade_engine.laya import DecisionStatus, Proposal, process_laya

    desk = mounted_desk
    runtime, calls = sidecar
    gate = process_laya()
    runtime.publish_status()
    assert gate.effective_status("live") is DecisionStatus.DOWN
    owner = desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(
        ("allow", "BUY", "Buy against the reviewed limit", "allow"),
        ("deny", "BUY", "A revenge order to chase losses", "deny"),
    ), max_age_seconds=10.0)
    report = owner.qualify()
    assert report["qualified"] is True and report["observed_effects"] == ["allow", "deny"]
    assert report["model_revision"] == "a" * 40
    assert report["source_revision"] and report["policy_revision"] and report["runtime_revision"]
    assert gate.effective_status("live") is DecisionStatus.READY
    captured = owner.capture()
    owner.revalidate(captured)
    proposal = Proposal("SYNTH", "NSE", "BUY", 1, "live", "LIMIT", "CNC", 4.0,
                        source="automate", rationale="Buy against the reviewed limit")
    assert gate.admit(proposal).allow
    assert sum(url.endswith("/v1/systemone") for url in calls) == 3
    owner.retire()
    with pytest.raises(ValueError, match="retired"):
        owner.revalidate(captured)
    assert not gate.admit(proposal).allow
    assert sum(url.endswith("/v1/systemone") for url in calls) == 3


@pytest.mark.parametrize("replacement", [
    "runtime", "weights", "policy", "configuration", "kill", "foreign-owner", "foreign-gate-owner", "client", "expired",
])
def test_qualification_refuses_replaced_or_expired_evidence(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    """A completed run never qualifies changed current runtime or factory custody.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        sidecar: Actual managed sidecar runtime and its inert HTTP request ledger.
        monkeypatch: Scoped replacements restored after this test.
        replacement: Runtime, owner or evidence substitution challenged after qualification.
    """
    import time
    from flinttrade_engine import laya_decision
    from flinttrade_engine.laya import DecisionStatus, process_laya

    runtime, calls = sidecar
    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    cases = (("allow", "BUY", "Reviewed limit", "allow"), ("deny", "BUY", "revenge", "deny"))
    owner.configure(cases=cases, max_age_seconds=0.2 if replacement == "expired" else 10.0)
    report = owner.qualify()
    assert report["qualified"] is True
    before = len(calls)
    if replacement == "runtime":
        runtime.start()
    elif replacement == "weights":
        (runtime.checkpoint_dir / laya_decision.load_policy().weight_file).write_bytes(b"changed")
    elif replacement == "policy":
        changed = replace(laya_decision.load_policy(), version="changed-policy")
        monkeypatch.setattr(laya_decision, "load_policy", lambda: changed)
    elif replacement == "configuration":
        owner.configure(cases=cases, max_age_seconds=11.0)
    elif replacement == "kill":
        mounted_desk.app.config["SAFETY"].l5_kill.activate("synthetic qualification retirement")
    elif replacement == "foreign-owner":
        mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"] = object()
    elif replacement == "foreign-gate-owner":
        from flinttrade_core.laya_qualification import LayaQualificationOwner

        gate = process_laya()
        gate.bind_qualification_owner(LayaQualificationOwner(mounted_desk.app, gate))
    elif replacement == "client":
        process_laya().set_decision_client(object())
    else:
        time.sleep(0.21)
    assert not owner.qualifies()
    assert process_laya().effective_status("live") is DecisionStatus.DOWN
    assert len(calls) == before


def test_rejected_and_missing_qualification_do_not_enable_the_gate(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]],
) -> None:
    """A failed raw HTTP observation and a mutated returned report remain non-authority.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        sidecar: Actual managed sidecar runtime and its inert HTTP request ledger.
    """
    from flinttrade_engine.laya import DecisionStatus, process_laya

    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    _runtime, calls = sidecar
    with pytest.raises(ValueError, match="not configured"):
        owner.qualify()
    assert calls == []
    owner.configure(cases=(("positive", "BUY", "revenge", "allow"),
                           ("negative", "BUY", "Reviewed limit", "deny")), max_age_seconds=10.0)
    report = owner.qualify()
    assert report["qualified"] is False and report["observed_effects"] == ["deny", "allow"]
    report["qualified"] = True
    assert not owner.qualifies()
    assert process_laya().effective_status("live") is DecisionStatus.DOWN


@pytest.mark.parametrize("operation", ["qualification", "decision"])
def test_late_external_response_cannot_survive_retirement(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """Retirement remains available during HTTP and rejects late successful bytes.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        sidecar: Actual managed sidecar runtime and its inert HTTP request ledger.
        monkeypatch: Scoped replacements restored after this test.
        operation: Public lifecycle or command operation exercised by this control.
    """
    import threading
    import urllib.request
    from flinttrade_engine.laya import Proposal, process_laya

    owner = mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"]
    owner.configure(cases=(("positive", "BUY", "Reviewed limit", "allow"),
                           ("negative", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    if operation == "decision":
        assert owner.qualify()["qualified"]
    entered, release = threading.Event(), threading.Event()
    original = urllib.request.urlopen
    outcomes: list[Any] = []

    def held(request: Any, **kwargs: Any) -> Any:
        if isinstance(request, urllib.request.Request) and request.full_url.endswith("/v1/systemone"):
            entered.set()
            assert release.wait(3)
        return original(request, **kwargs)

    def work() -> None:
        try:
            outcomes.append(owner.qualify() if operation == "qualification" else process_laya().admit(
                Proposal("SYNTH", "NSE", "BUY", 1, "live", "LIMIT", "CNC", 4.0,
                         source="automate", rationale="Reviewed limit")))
        except ValueError as exc:
            outcomes.append(exc)

    monkeypatch.setattr(urllib.request, "urlopen", held)
    thread = threading.Thread(target=work)
    thread.start()
    try:
        assert entered.wait(3)
        owner.retire()
        assert not owner.qualifies()
    finally:
        release.set()
        thread.join(4)
    assert not thread.is_alive() and len(outcomes) == 1
    if operation == "qualification":
        assert isinstance(outcomes[0], ValueError)
    else:
        assert outcomes[0].allow is False
