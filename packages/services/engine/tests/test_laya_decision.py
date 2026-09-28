"""Free-text admission against a fake decision host.

Thresholds use probabilities. A host failure is Down. The host cannot raise
a quantity or overturn a floor refusal.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from flinttrade_engine.laya import DecisionStatus, Laya, Proposal
from flinttrade_engine.laya_decision import (
    DecisionCallError,
    SystemOneClient,
    load_policy,
    questions_for_note,
)

_POLICY = load_policy()


class FakeLayaHost:
    """Loopback ``/v1/systemone`` stand-in. No model is loaded."""

    def __init__(self) -> None:
        self.requests: list[bytes] = []
        self.headers: list[dict[str, str]] = []
        self.response_code = 200
        self.response_body = b"{}"
        self.delay = 0.0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        host = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0") or 0)
                host.requests.append(self.rfile.read(length))
                host.headers.append({key: value for key, value in self.headers.items()})
                if host.delay:
                    time.sleep(host.delay)
                body = host.response_body
                self.send_response(host.response_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        assert self._httpd is not None
        _host, port = self._httpd.server_address[:2]
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2)


@pytest.fixture
def laya_host() -> Any:
    host = FakeLayaHost()
    host.start()
    yield host
    host.stop()


def _proposal(**overrides: Any) -> Proposal:
    quantity = overrides.get("quantity", 4)
    return Proposal(
        symbol=str(overrides.get("symbol", "RELIANCE")),
        exchange=str(overrides.get("exchange", "NSE")),
        action=str(overrides.get("action", "BUY")),
        quantity=quantity if isinstance(quantity, int) else 4,
        mode=str(overrides.get("mode", "practice")),
        order_type=str(overrides.get("order_type", "MARKET")),
        product=str(overrides.get("product", "MIS")),
        source=str(overrides.get("source", "operator")),
        price=overrides.get("price"),
        rationale=str(overrides.get("rationale", "Buying the planned breakout.")),
    )


def _choice(deny_key: str, deny_p: float, *, confidence: float = 0.99) -> dict[str, object]:
    other = "A" if deny_key == "B" else "B"
    return {
        "choice": other,
        "probabilities": {deny_key: deny_p, other: round(1 - deny_p, 6)},
        "confidence": confidence,
    }


def _answers(*, rationale_b: float = 0.1, tilt_a: float = 0.1, side_a: float = 0.1) -> dict[str, object]:
    return {
        "rationale": _choice("B", rationale_b),
        "tilt": _choice("A", tilt_a),
        "side": _choice("A", side_a),
    }


def _body(answers: dict[str, object], **extra: object) -> bytes:
    payload: dict[str, object] = {
        "revision": _POLICY.revision,
        "sha256": _POLICY.sha256,
        "answers": answers,
    }
    payload.update(extra)
    return json.dumps(payload).encode("utf-8")


def _engine(host: FakeLayaHost, *, timeout: float = 1.0, status: DecisionStatus = DecisionStatus.READY) -> Laya:
    engine = Laya(status=status, max_quantity=100, degraded_max_quantity=1)
    engine.set_decision_client(
        SystemOneClient(
            host.url,
            api_key="test-key",
            timeout=timeout,
            expected_revision=_POLICY.revision,
            expected_sha256=_POLICY.sha256,
        )
    )
    return engine


def _posted(host: FakeLayaHost) -> dict[str, Any]:
    assert host.requests
    return json.loads(host.requests[-1])


@pytest.mark.unit
def test_policy_pins_revision_and_probabilities_not_confidence() -> None:
    policy = load_policy()
    assert policy.version == "1"
    assert policy.repo == "convaiinnovations/laya"
    assert policy.revision == "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
    assert policy.sha256 == "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"
    assert [rule.question_id for rule in policy.questions] == ["rationale", "tilt", "side"]
    assert all(rule.abstain_at < rule.deny_at for rule in policy.questions)


@pytest.mark.unit
def test_probability_at_the_deny_threshold_denies(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(tilt_a=0.80))
    verdict = _engine(laya_host).admit(_proposal())
    assert verdict.allow is False
    assert "tilt or revenge" in verdict.reason


@pytest.mark.unit
def test_probability_just_below_deny_clamps_in_practice(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(tilt_a=0.79))
    verdict = _engine(laya_host).admit(_proposal(quantity=4))
    assert verdict.allow is True
    assert verdict.tightened is True
    assert verdict.applied_quantity == 1
    assert verdict.applied_quantity < 4


@pytest.mark.unit
def test_probability_just_below_abstain_allows(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(rationale_b=0.54, tilt_a=0.54, side_a=0.54))
    verdict = _engine(laya_host).admit(_proposal(quantity=4))
    assert verdict.allow is True
    assert verdict.tightened is False
    assert verdict.applied_quantity == 4


@pytest.mark.unit
def test_probability_just_above_deny_denies(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(side_a=0.81))
    verdict = _engine(laya_host).admit(_proposal(mode="live"))
    assert verdict.allow is False
    assert "contradicts the order side" in verdict.reason


@pytest.mark.unit
def test_uncertain_answer_denies_in_live(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(rationale_b=0.60))
    verdict = _engine(laya_host).admit(_proposal(mode="live", quantity=4))
    assert verdict.allow is False
    assert verdict.reason == "Laya is uncertain. Live orders are blocked."


@pytest.mark.unit
def test_confidence_field_is_ignored(laya_host: FakeLayaHost) -> None:
    answers = _answers()
    answers["tilt"] = {
        "choice": "B",
        "probabilities": {"A": 0.91, "B": 0.09},
        "confidence": 0.01,
    }
    laya_host.response_body = _body(answers)
    verdict = _engine(laya_host).admit(_proposal())
    assert verdict.allow is False
    assert "tilt or revenge" in verdict.reason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("code", "body", "failure"),
    [
        (401, b'{"detail":"no"}', "http_401"),
        (422, b'{"detail":"bad question"}', "http_422"),
        (503, b'{"detail":"busy"}', "http_503"),
        (200, b"{", "malformed"),
        (200, _body({"rationale": _choice("B", 0.1)}), "missing_answer"),
    ],
)
def test_http_failures_are_down(laya_host: FakeLayaHost, code: int, body: bytes, failure: str) -> None:
    laya_host.response_code = code
    laya_host.response_body = body
    engine = _engine(laya_host)
    verdict = engine.admit(_proposal(mode="practice"))
    assert verdict.allow is False
    assert "Practice orders are blocked" in verdict.reason
    assert engine.status is DecisionStatus.DOWN
    assert ("failure", failure) in verdict.evidence


@pytest.mark.unit
def test_timeout_is_down(laya_host: FakeLayaHost) -> None:
    laya_host.delay = 1.0
    laya_host.response_body = _body(_answers())
    engine = _engine(laya_host, timeout=0.05)
    verdict = engine.admit(_proposal())
    assert verdict.allow is False
    assert engine.status is DecisionStatus.DOWN
    assert ("failure", "timeout") in verdict.evidence


@pytest.mark.unit
def test_connection_refused_is_down() -> None:
    engine = Laya(status=DecisionStatus.READY)
    engine.set_decision_client(
        SystemOneClient(
            "http://127.0.0.1:9",
            api_key="test-key",
            timeout=0.2,
            expected_revision=_POLICY.revision,
            expected_sha256=_POLICY.sha256,
        )
    )
    verdict = engine.admit(_proposal())
    assert verdict.allow is False
    assert engine.status is DecisionStatus.DOWN
    assert ("failure", "connection") in verdict.evidence


@pytest.mark.unit
def test_revision_mismatch_is_down(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(), revision="0" * 40)
    engine = _engine(laya_host)
    verdict = engine.admit(_proposal(mode="live"))
    assert verdict.allow is False
    assert "Live orders are blocked" in verdict.reason
    assert ("failure", "revision_mismatch") in verdict.evidence


@pytest.mark.unit
def test_digest_mismatch_is_down(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(), sha256="ab" * 32)
    engine = _engine(laya_host)
    verdict = engine.admit(_proposal())
    assert ("failure", "digest_mismatch") in verdict.evidence
    assert engine.status is DecisionStatus.DOWN


@pytest.mark.unit
def test_host_cannot_raise_quantity_or_skip_the_ceiling(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers(), applied_quantity=999)
    verdict = _engine(laya_host).admit(_proposal(quantity=150))
    assert verdict.allow is True
    assert verdict.applied_quantity == 100
    assert verdict.applied_quantity < 150


@pytest.mark.unit
def test_floor_refusal_does_not_call_the_host(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers())
    engine = _engine(laya_host)
    missing_price = engine.admit(_proposal(order_type="LIMIT", price=None))
    chat = engine.admit(_proposal(source="chat"))
    explore = engine.admit(_proposal(mode="explore"))
    assert missing_price.allow is False
    assert chat.allow is False
    assert explore.allow is False
    assert laya_host.requests == []


@pytest.mark.unit
def test_empty_note_does_not_call_the_host(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers())
    verdict = _engine(laya_host).admit(_proposal(rationale="  "))
    assert verdict.allow is False
    assert "concrete reason" in verdict.reason
    assert laya_host.requests == []
    fresh = _engine(laya_host)
    fresh.admit(_proposal(rationale=""))
    assert fresh.status is DecisionStatus.READY


@pytest.mark.unit
def test_questions_omit_facts_the_floor_already_knows(laya_host: FakeLayaHost) -> None:
    laya_host.response_body = _body(_answers())
    _engine(laya_host).admit(_proposal(symbol="RELIANCE", quantity=7, rationale="Planned breakout only."))
    posted = _posted(laya_host)
    encoded = json.dumps(posted)
    assert posted["questions"].keys() == questions_for_note().keys()
    assert "RELIANCE" not in encoded
    assert "expiry" not in encoded.lower()
    assert "quantity" not in encoded.lower()
    for question in posted["questions"].values():
        assert question["type"] == "choice"
        assert set(question["criteria"]) == {"A", "B"}
    assert laya_host.headers[-1]["Authorization"] == "Bearer test-key"


@pytest.mark.unit
def test_client_rejects_an_unusable_origin() -> None:
    with pytest.raises(ValueError):
        SystemOneClient(
            "http://0.0.0.0:8888",
            expected_revision=_POLICY.revision,
            expected_sha256=_POLICY.sha256,
        )
    client = SystemOneClient(
        "http://127.0.0.1:8888",
        api_key="sk-test",
        expected_revision=_POLICY.revision,
        expected_sha256=_POLICY.sha256,
    )
    assert client.base_url == "http://127.0.0.1:8888"


@pytest.mark.unit
def test_decision_call_error_code_is_stable() -> None:
    error = DecisionCallError("timeout")
    assert error.code == "timeout"
