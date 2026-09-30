"""Ollama route for the Laya gate. The sidecar stays the default."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_engine.laya import (
    LAYA_DOWN_REASON,
    DecisionStatus,
    Laya,
    Proposal,
    laya_reason_detail,
)
from flinttrade_engine.laya_benchmark import run_fail_closed_drills
from flinttrade_engine.laya_decision import state_for_note
from flinttrade_engine.laya_ollama import (
    LayaOllamaModel,
    OllamaDecisionClient,
    reset_laya_backend_warning_for_tests,
    reset_laya_ollama_transport_for_tests,
    set_laya_ollama_transport_for_tests,
)

_DIGEST = "ab" * 32
_TAG = "example:bench"
_HIDDEN = "EXAMPLE-HIDDEN-SYMBOL"
_NOTE = "Buying because the EXAMPLE level 100 held."
_SOURCE = Path(__file__).resolve().parents[1] / "src" / "flinttrade_engine" / "laya_ollama.py"


def _proposal(rationale: str, *, mode: str = "practice", action: str = "BUY") -> Proposal:
    return Proposal(
        symbol=_HIDDEN,
        exchange="NFO",
        action=action,
        quantity=20,
        mode=mode,
        rationale=rationale,
    )


def _allow_answers() -> dict[str, Any]:
    return {
        "answers": {
            "rationale": {"probabilities": {"A": 0.9, "B": 0.1}},
            "tilt": {"probabilities": {"A": 0.1, "B": 0.9}},
            "side": {"probabilities": {"A": 0.1, "B": 0.9}},
        }
    }


def _chat_body(answers: Mapping[str, Any] | None = None) -> dict[str, Any]:
    import json

    payload = answers if answers is not None else _allow_answers()
    return {"message": {"content": json.dumps(payload)}}


@contextmanager
def _ready(route: str, poster: Any, *, version: str = "0.35.0", session_digest: str = _DIGEST, present: bool = True):
    import flinttrade_engine.laya_ollama as ollama_mod

    saved = ollama_mod.LAYA_OLLAMA_ALLOWLIST
    ollama_mod.LAYA_OLLAMA_ALLOWLIST = (LayaOllamaModel(tag=_TAG, digest=_DIGEST, route=route),)

    @contextmanager
    def session(model: str):
        del model
        yield SimpleNamespace(
            digest=session_digest,
            base_url="http://127.0.0.1:11435",
            model=f"flinttrade/sha256-{session_digest}:locked",
        )

    snapshot = {
        "state": "ready",
        "ready": True,
        "model_present": present,
        "reported_digest": _DIGEST,
        "pinned_server_version": version,
        "port": 11435,
    }
    set_laya_ollama_transport_for_tests(session=session, poster=poster, snapshot=lambda _model: snapshot)
    try:
        yield
    finally:
        ollama_mod.LAYA_OLLAMA_ALLOWLIST = saved
        reset_laya_ollama_transport_for_tests()


class _Sentinel:
    def __init__(self) -> None:
        self.calls = 0
        self.last_proof = "decision"

    def decide(self, state: str, questions: object) -> dict[str, Any]:
        del questions
        self.calls += 1
        assert _HIDDEN not in state
        return _allow_answers()


@pytest.mark.unit
def test_flag_off_keeps_the_sidecar_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLINTTRADE_LAYA_BACKEND", raising=False)

    def explode(model: str):
        del model
        raise AssertionError("sidecar must not open Ollama")

    monkeypatch.setattr("flinttrade_core.ollama_runtime.managed_ollama_session", explode)
    client = _Sentinel()
    engine = Laya(status=DecisionStatus.READY)
    engine.set_decision_client(client)
    verdict = engine.admit(_proposal(_NOTE))
    assert verdict.allow is True
    assert client.calls == 1


@pytest.mark.unit
def test_explicit_sidecar_matches_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "SIDECAR")
    client = _Sentinel()
    engine = Laya(status=DecisionStatus.READY)
    engine.set_decision_client(client)
    assert engine.admit(_proposal(_NOTE)).allow is True
    assert client.calls == 1


@pytest.mark.unit
def test_unknown_backend_pauses_new_orders(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    reset_laya_backend_warning_for_tests()
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "typo")
    client = _Sentinel()
    engine = Laya(status=DecisionStatus.READY)
    engine.set_decision_client(client)
    with caplog.at_level(logging.WARNING, logger="flinttrade.engine.laya_ollama"):
        first = engine.admit(_proposal(_NOTE))
        second = engine.admit(_proposal(_NOTE))
    assert first.allow is False
    assert first.reason == LAYA_DOWN_REASON
    assert second.reason == LAYA_DOWN_REASON
    assert client.calls == 0
    assert caplog.text.count("not sidecar or ollama") == 1
    reset_laya_backend_warning_for_tests()


@pytest.mark.unit
def test_fail_closed_drills_refuse_and_still_close() -> None:
    drills = {drill.name: drill for drill in run_fail_closed_drills()}
    assert set(drills) == {
        "ollama_stopped",
        "model_missing",
        "wrong_digest",
        "timeout",
        "malformed_output",
        "oversized_prompt",
        "note_too_long",
        "empty_note_live",
        "runtime_too_old",
        "advisory_choices",
    }
    for drill in drills.values():
        assert drill.ended in {"down", "refusal"}
        assert drill.close_allowed is True
    assert drills["wrong_digest"].detail == "Wrong model version"
    assert drills["model_missing"].detail == "Downloading the model · 0.0 of 0.0 GB"
    assert drills["timeout"].detail == "Unreachable"
    assert drills["ollama_stopped"].detail == "Not started"
    assert drills["runtime_too_old"].detail == "Can't verify the model"
    assert drills["note_too_long"].detail == "The note is too long to admit."
    assert drills["oversized_prompt"].detail == "prompt_over_cap"
    assert drills["empty_note_live"].detail == "note_absent"


@pytest.mark.unit
def test_chat_and_systemone_send_only_the_side_and_the_note(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "ollama")
    monkeypatch.setenv("FLINTTRADE_LAYA_OLLAMA_MODEL", _TAG)
    seen: dict[str, Any] = {}

    def chat_poster(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
        del base_url, timeout
        seen["path"] = path
        seen["user"] = payload["messages"][1]["content"]
        seen["system"] = payload["messages"][0]["content"]
        return _chat_body()

    with _ready("chat", chat_poster):
        engine = Laya(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(_NOTE))
    assert verdict.allow is True
    assert seen["path"] == "/api/chat"
    assert seen["user"] == state_for_note(action="BUY", rationale=_NOTE)
    assert _HIDDEN not in seen["user"]
    assert "quantity" not in str(seen["user"]).lower()
    assert "quantity" not in str(seen["system"]).lower()
    assert "20" not in seen["user"]

    def systemone_poster(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
        del base_url, timeout
        seen["path"] = path
        seen["state"] = payload["state"]
        seen["model"] = payload["model"]
        return _allow_answers()

    with _ready("systemone", systemone_poster):
        engine = Laya(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(_NOTE, action="SELL"))
    assert verdict.allow is True
    assert seen["path"] == "/v1/systemone"
    assert seen["state"] == state_for_note(action="SELL", rationale=_NOTE)
    assert seen["model"] == f"flinttrade/sha256-{_DIGEST}:locked"
    assert _HIDDEN not in seen["state"]


@pytest.mark.unit
def test_exactly_4000_reaches_the_model_and_4001_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "ollama")
    monkeypatch.setenv("FLINTTRADE_LAYA_OLLAMA_MODEL", _TAG)
    calls: list[str] = []
    prefix = "Buying because the EXAMPLE level 100 held. "
    exact = prefix + ("x" * (4000 - len(prefix)))
    over = prefix + ("y" * (4001 - len(prefix)))
    padded = "\n\n" + exact + " \t"

    def poster(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
        del base_url, timeout
        calls.append(payload["messages"][1]["content"])
        return _chat_body()

    with _ready("chat", poster):
        engine = Laya(status=DecisionStatus.READY)
        admitted = engine.admit(_proposal(exact))
        padded_verdict = engine.admit(_proposal(padded))
        refused = engine.admit(_proposal(over))
        empty = engine.admit(_proposal("   "))
    assert admitted.allow is True
    assert padded_verdict.allow is True
    assert len(calls) == 2
    assert calls[0].endswith(exact)
    assert "Note:\n" + exact in calls[1]
    assert refused.allow is False
    assert refused.reason == "The note is too long to admit."
    assert engine.status is DecisionStatus.READY
    assert empty.allow is True
    assert empty.tightened is True
    assert empty.applied_quantity == 1
    assert len(calls) == 2


@pytest.mark.unit
def test_confidence_does_not_decide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLINTTRADE_LAYA_BACKEND", "ollama")
    monkeypatch.setenv("FLINTTRADE_LAYA_OLLAMA_MODEL", _TAG)

    def body(deny_b: float, confidence: float) -> dict[str, Any]:
        return {
            "answers": {
                "rationale": {"probabilities": {"A": 1 - deny_b, "B": deny_b}, "confidence": confidence},
                "tilt": {"probabilities": {"A": 0.1, "B": 0.9}, "confidence": confidence},
                "side": {"probabilities": {"A": 0.1, "B": 0.9}, "confidence": confidence},
            }
        }

    def allow_poster(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
        del base_url, path, payload, timeout
        return body(0.1, 0.99)

    with _ready("systemone", allow_poster):
        allowed = Laya(status=DecisionStatus.READY).admit(_proposal(_NOTE))
    assert allowed.allow is True

    def deny_poster(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
        del base_url, path, payload, timeout
        return body(0.95, 0.01)

    with _ready("systemone", deny_poster):
        refused = Laya(status=DecisionStatus.READY).admit(_proposal(_NOTE))
    assert refused.allow is False
    assert refused.reason != LAYA_DOWN_REASON


@pytest.mark.unit
def test_gate_source_does_not_call_the_advisory_client() -> None:
    text = _SOURCE.read_text(encoding="utf-8")
    assert "llm_client" not in text
    assert "flinttrade_ai" not in text
    assert "/v1/chat/completions" not in text


@pytest.mark.unit
def test_digest_mismatch_copy_is_wrong_model_version() -> None:
    assert laya_reason_detail("wrong_revision", 11435) == "Wrong model version"
    client = OllamaDecisionClient(
        LayaOllamaModel(tag=_TAG, digest=_DIGEST, route="chat"),
        server_version="0.35.0",
    )
    assert client.last_proof == ""
