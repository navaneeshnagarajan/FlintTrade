"""Admission and HTTP regressions using only synthetic, local in-memory transports."""

from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.response import addinfourl

import pytest

from flinttrade_engine import laya_ollama as ollama
from flinttrade_engine.laya import LAYA_DOWN_REASON, DecisionStatus, Laya, Proposal
from flinttrade_engine.laya_decision import DecisionCallError, questions_for_note

_DIGEST = "ab" * 32
_TAG = "example:transport-test"
_ALIAS = f"flinttrade/sha256-{_DIGEST}:locked"
_BASE = "http://127.0.0.1:11435"


def _body():
    return {"message": {"content": json.dumps({"answers": {
        "rationale": {"probabilities": {"A": 0.9, "B": 0.1}},
        "tilt": {"probabilities": {"A": 0.1, "B": 0.9}},
        "side": {"probabilities": {"A": 0.1, "B": 0.9}},
    }})}}


def _entry():
    return ollama.LayaOllamaModel(tag=_TAG, digest=_DIGEST, route="chat")


@contextmanager
def _session(_model):
    yield SimpleNamespace(model=_ALIAS, digest=_DIGEST, base_url=_BASE)


@pytest.fixture(autouse=True)
def _restore_transport():
    ollama.reset_laya_ollama_transport_for_tests()
    yield
    ollama.reset_laya_ollama_transport_for_tests()


@pytest.mark.unit
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("location", [
    "http://example.invalid/decision", "http://127.0.0.1:11436/api/chat", "/api/chat",
])
def test_redirect_is_rejected_before_any_second_request(monkeypatch, status, location):
    seen = []
    responses = []

    class MemoryHTTPHandler(urllib.request.HTTPHandler):
        handler_order = 100

        def http_open(self, request):
            seen.append(request.full_url)
            response = addinfourl(
                io.BytesIO(b"" if len(seen) == 1 else json.dumps(_body()).encode()),
                {"location": location} if len(seen) == 1 else {},
                request.full_url,
                status if len(seen) == 1 else 200,
            )
            response.msg = "Synthetic response"
            responses.append(response)
            return response

    build = urllib.request.build_opener
    monkeypatch.setattr(ollama.urllib.request, "build_opener", lambda *handlers: build(*handlers, MemoryHTTPHandler()))
    with pytest.raises(DecisionCallError):
        ollama._post_loopback(_BASE, "/api/chat", {}, 3.0)
    assert seen == [f"{_BASE}/api/chat"]
    assert all(response.closed for response in responses)


@pytest.mark.unit
@pytest.mark.parametrize("phase", ["headers", "body", "chunked_body"])
def test_trickling_http_response_expires_at_total_deadline(monkeypatch, phase):
    """Exercise actual urllib/HTTPResponse I/O without connecting or listening."""
    read_sock, write_sock = socket.socketpair()
    class LocalSocket:
        def __getattr__(self, name):
            return getattr(read_sock, name)

        def setsockopt(self, *_args):
            pass  # HTTPConnection's TCP_NODELAY has no meaning on a socketpair.

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: LocalSocket())
    payload = json.dumps(_body()).encode()
    if phase == "chunked_body":
        header = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        parts = [f"{len(payload):x}\r\n".encode(), *[payload[i:i + 12] for i in range(0, len(payload), 12)], b"\r\n0\r\n\r\n"]
    else:
        header = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
        parts = [header[i:i + 4] for i in range(0, len(header), 4)] + [payload] if phase == "headers" else [
            payload[i:i + 12] for i in range(0, len(payload), 12)
        ]
    if phase != "headers":
        write_sock.sendall(header)
    stopped = threading.Event()

    def write_fragments():
        try:
            for part in parts:
                if stopped.wait(0.02):
                    return
                write_sock.sendall(part)
        except OSError:
            pass  # The client closes its timed-out response.
        finally:
            write_sock.close()

    writer = threading.Thread(target=write_fragments)
    writer.start()
    started = time.monotonic()
    try:
        with pytest.raises(DecisionCallError, match="^timeout$"):
            ollama._post_loopback(_BASE, "/api/chat", {}, 0.12)
        assert time.monotonic() - started < 0.3
    finally:
        stopped.set()
        read_sock.close()
        writer.join(timeout=1.0)
    assert not writer.is_alive()


class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, amount):
        self.now += amount


@pytest.mark.unit
@pytest.mark.parametrize("phase", ["entry", "request", "post", "normalisation", "exit"])
def test_entire_admission_must_finish_before_deadline(monkeypatch, phase):
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    calls = []
    exited = []

    @contextmanager
    def session(model):
        if phase == "entry":
            clock.advance(3.0)
        try:
            with _session(model) as admission:
                yield admission
        finally:
            exited.append(True)
            if phase == "exit":
                clock.advance(3.0)

    def poster(*_args):
        calls.append(True)
        if phase == "post":
            clock.advance(3.0)
        return _body()

    target_name = "_request_for" if phase == "request" else "normalise_decision_payload"
    original = getattr(ollama, target_name)

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        if phase in {"request", "normalisation"}:
            clock.advance(3.0)
        return result

    monkeypatch.setattr(ollama, target_name, delayed)
    ollama.set_laya_ollama_transport_for_tests(session=session, poster=poster)
    client = ollama.OllamaDecisionClient(_entry())
    with pytest.raises(DecisionCallError, match="^timeout$"):
        client.decide("Synthetic note", questions_for_note())
    assert client.last_proof == ""
    assert exited == [True]
    if phase in {"entry", "request"}:
        assert calls == []


@pytest.mark.unit
def test_request_uses_only_budget_remaining_after_admission(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    budgets = []

    @contextmanager
    def session(model):
        clock.advance(1.25)
        with _session(model) as admission:
            yield admission

    def poster(_base, _path, _payload, timeout):
        budgets.append(timeout)
        return _body()

    ollama.set_laya_ollama_transport_for_tests(session=session, poster=poster)
    client = ollama.OllamaDecisionClient(_entry())
    assert "answers" in client.decide("Synthetic note", questions_for_note())
    assert budgets == [pytest.approx(1.75)]
    assert client.last_proof == "runtime"


@pytest.mark.unit
@pytest.mark.parametrize("model", [_TAG, f"flinttrade/sha256-{'cd' * 32}:locked", "arbitrary"])
def test_matching_digest_cannot_admit_a_different_model_name(model):
    @contextmanager
    def session(_model):
        yield SimpleNamespace(model=model, digest=_DIGEST, base_url=_BASE)

    ollama.set_laya_ollama_transport_for_tests(
        session=session, poster=lambda *_args: pytest.fail("unbound model must not be called"),
    )
    client = ollama.OllamaDecisionClient(_entry())
    with pytest.raises(DecisionCallError, match="^digest_mismatch$"):
        client.decide("Synthetic note", questions_for_note())
    assert client.last_proof == ""


@pytest.mark.unit
def test_production_session_receives_reviewed_source_and_digest(monkeypatch):
    from flinttrade_core import ollama_runtime

    seen = []

    @contextmanager
    def gate_session(model, digest, *, deadline):
        assert 0 < deadline - time.monotonic() <= 3.0
        seen.append((model, digest))
        with _session(model) as admission:
            yield admission

    monkeypatch.setattr(ollama_runtime, "managed_ollama_gate_session", gate_session, raising=False)
    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", lambda *_args: pytest.fail("mutable source admission"))
    ollama.set_laya_ollama_transport_for_tests(session=None, poster=lambda *_args: _body())
    client = ollama.OllamaDecisionClient(_entry())
    assert "answers" in client.decide("Synthetic note", questions_for_note())
    assert seen == [(_TAG, _DIGEST)]
    assert client.last_proof == "runtime"


@pytest.mark.unit
def test_gate_network_budget_is_context_local_and_restored_after_failure(monkeypatch):
    import contextvars

    from flinttrade_core import ollama_runtime

    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    timeouts = []

    def opened(_request, *, timeout):
        timeouts.append(timeout)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(ollama_runtime, "_open_loopback_request", opened)

    def read():
        return ollama_runtime._request_ollama_json("GET", "/api/tags", None, base_url=_BASE)

    with pytest.raises(TimeoutError):
        with ollama_runtime._gate_request_budget(clock() + 0.1):
            assert read() == {}
            assert contextvars.Context().run(read) == {}
            with ollama_runtime._gate_request_budget(clock() + 10):
                clock.advance(0.1)
                read()
    assert read() == {}
    assert timeouts == pytest.approx([0.1, 10.0, 10.0])


@pytest.mark.unit
def test_version_probe_respects_the_enclosing_gate_budget(monkeypatch):
    from flinttrade_core import ollama_runtime

    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    timeouts = []

    def stalled_connect(_address, *, timeout):
        timeouts.append(timeout)
        clock.advance(timeout)
        raise TimeoutError("synthetic version stall")

    monkeypatch.setattr(socket, "create_connection", stalled_connect)
    with pytest.raises(TimeoutError):
        with ollama_runtime._gate_request_budget(clock() + 0.1):
            assert ollama_runtime._probe_ollama_server(_BASE) is None
    assert timeouts == pytest.approx([0.1])


@pytest.mark.unit
@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0.0, -1.0])
def test_decision_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="timeout"):
        ollama.OllamaDecisionClient(_entry(), timeout=timeout)


@pytest.mark.unit
def test_late_decision_pauses_new_orders_and_preserves_reduce_only(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    monkeypatch.setenv(ollama.BACKEND_ENV, "ollama")
    monkeypatch.setenv(ollama.MODEL_ENV, _TAG)
    monkeypatch.setattr(ollama, "LAYA_OLLAMA_ALLOWLIST", (_entry(),))

    def poster(*_args):
        clock.advance(3.0)
        return _body()

    ollama.set_laya_ollama_transport_for_tests(session=_session, poster=poster, snapshot=lambda _model: {
        "state": "ready", "ready": True, "model_present": True,
        "reported_digest": _DIGEST, "pinned_server_version": "0.35.0", "port": 11435,
    })
    engine = Laya(status=DecisionStatus.READY)
    proposal = Proposal(symbol="EXAMPLE", exchange="NFO", action="BUY", quantity=1, mode="practice",
                        rationale="Buying because the EXAMPLE level 100 held.")
    verdict = engine.admit(proposal)
    assert verdict.allow is False
    assert verdict.reason == LAYA_DOWN_REASON
    assert engine.status is DecisionStatus.DOWN
    assert engine.admit_reduce_only(proposal).allow is True


def _memory_response(monkeypatch, raw, status=200):
    responses = []

    class MemoryHTTPHandler(urllib.request.HTTPHandler):
        handler_order = 100

        def http_open(self, request):
            assert request.full_url == f"{_BASE}/api/chat"
            assert not request.has_proxy()
            response = addinfourl(io.BytesIO(raw), {}, request.full_url, status)
            response.msg = "Synthetic response"
            responses.append(response)
            return response

    build = urllib.request.build_opener
    monkeypatch.setattr(ollama.urllib.request, "build_opener", lambda *handlers: build(*handlers, MemoryHTTPHandler()))
    return responses


@pytest.mark.unit
def test_http_error_closes_its_response(monkeypatch):
    responses = _memory_response(monkeypatch, b"unavailable", status=503)
    with pytest.raises(DecisionCallError, match="^http_503$"):
        ollama._post_loopback(_BASE, "/api/chat", {}, 3.0)
    assert responses[0].closed


@pytest.mark.unit
@pytest.mark.parametrize("extra", [0, 1])
def test_response_limit_is_still_enforced_with_proxies_disabled(monkeypatch, extra):
    monkeypatch.setenv("http_proxy", "http://example.invalid:9999")
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:9999")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    responses = _memory_response(monkeypatch, b"{}" + b" " * (ollama._MAX_RESPONSE_BYTES - 2 + extra))
    if extra:
        with pytest.raises(DecisionCallError, match="^malformed$"):
            ollama._post_loopback(_BASE, "/api/chat", {}, 3.0)
    else:
        assert ollama._post_loopback(_BASE, "/api/chat", {}, 3.0) == {}
    assert responses[0].closed


@pytest.mark.unit
@pytest.mark.parametrize("base", [
    "https://127.0.0.1:11435", "http://localhost:11435", "http://example.invalid:11435",
    "http://user@127.0.0.1:11435", "http://127.0.0.1:11435/elsewhere",
    "http://127.0.0.1:11435?query=value", "http://127.0.0.1:11435#fragment", "http://127.0.0.1",
])
def test_transport_rejects_non_admitted_base_before_open(monkeypatch, base):
    monkeypatch.setattr(ollama.urllib.request, "build_opener", lambda *_args: pytest.fail("invalid origin opened"))
    with pytest.raises(DecisionCallError, match="^connection$"):
        ollama._post_loopback(base, "/api/chat", {}, 3.0)


@pytest.mark.unit
def test_http_json_decoding_is_inside_the_deadline(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(time, "monotonic", clock)
    _memory_response(monkeypatch, b"{}")
    loads = json.loads

    def late_decode(*args, **kwargs):
        decoded = loads(*args, **kwargs)
        clock.advance(3.0)
        return decoded

    monkeypatch.setattr(json, "loads", late_decode)
    with pytest.raises(DecisionCallError, match="^timeout$"):
        ollama._post_loopback(_BASE, "/api/chat", {}, 3.0)


@pytest.mark.unit
def test_exit_verification_error_never_leaves_an_old_runtime_proof():
    client = ollama.OllamaDecisionClient(_entry())
    ollama.set_laya_ollama_transport_for_tests(session=_session, poster=lambda *_args: _body())
    client.decide("Synthetic note", questions_for_note())
    assert client.last_proof == "runtime"

    @contextmanager
    def changed(model):
        with _session(model) as admission:
            yield admission
        raise RuntimeError("model digest changed at exit")

    ollama.set_laya_ollama_transport_for_tests(session=changed, poster=lambda *_args: _body())
    with pytest.raises(DecisionCallError, match="^digest_mismatch$"):
        client.decide("Synthetic note", questions_for_note())
    assert client.last_proof == ""


@pytest.mark.unit
@pytest.mark.parametrize("framing", ["content_length", "chunked", "eof"])
def test_complete_http_response_within_budget_is_usable(monkeypatch, framing):
    read_sock, write_sock = socket.socketpair()

    class LocalSocket:
        def __getattr__(self, name):
            return getattr(read_sock, name)

        def setsockopt(self, *_args):
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: LocalSocket())
    payload = json.dumps(_body()).encode()
    if framing == "chunked":
        headers = b"Transfer-Encoding: chunked\r\n"
        body = f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n"
    else:
        headers = b"Content-Length: " + str(len(payload)).encode() + b"\r\n" if framing == "content_length" else b""
        body = payload
    write_sock.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n" + headers + b"\r\n" + body)
    write_sock.shutdown(socket.SHUT_WR)
    try:
        assert ollama._post_loopback(_BASE, "/api/chat", {}, 3.0) == _body()
        assert read_sock.fileno() == -1
    finally:
        read_sock.close()
        write_sock.close()
