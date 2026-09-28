"""Typed free-text questions for the Laya place gate.

The model is asked only about text the deterministic floor cannot score:
whether a note states a concrete reason, whether it shows tilt or revenge,
and whether the stated plan contradicts the order side. Expiry, quantity,
price, and symbol stay outside the question set.

Thresholds read option probabilities. A verdict can deny or clamp. It cannot
raise a quantity or overturn a floor refusal. An unreachable host, a timeout,
a bad response, or a revision or digest mismatch is Down.
"""

from __future__ import annotations

import json
import math
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from flinttrade_core.service_providers import EvidenceUseScope

from .laya import DecisionStatus

_QUESTION_ORDER = ("rationale", "tilt", "side")
_MAX_NOTE_CHARS = 4_000
_MAX_RESPONSE_BYTES = 1_000_000
_NEUTRAL_KEYS = ("A", "B")


class DecisionCallError(Exception):
    """The decision host did not return a usable verdict.

    ``code`` is a stable token for logs. It is not operator copy.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class QuestionRule:
    """Probability thresholds for one typed question."""

    question_id: str
    deny_option: str
    deny_at: float
    abstain_at: float


@dataclass(frozen=True, slots=True)
class LayaPolicy:
    """Versioned checkpoint pin and probability thresholds."""

    version: str
    repo: str
    revision: str
    checkpoint: str
    weight_file: str
    sha256: str
    questions: tuple[QuestionRule, ...]

    def rule(self, question_id: str) -> QuestionRule:
        """Return the rule for ``question_id``."""
        for rule in self.questions:
            if rule.question_id == question_id:
                return rule
        raise KeyError(question_id)


@dataclass(frozen=True, slots=True)
class LayaQualification:
    """Evidence that one checkpoint revision and policy version may admit Live.

    ``scope`` uses :class:`EvidenceUseScope`. Only ``live_decision`` for the
    exact revision, weight digest, and policy version opens Live.
    """

    revision: str
    policy_version: str
    sha256: str
    scope: EvidenceUseScope

    def __post_init__(self) -> None:
        if type(self.scope) is not EvidenceUseScope:
            raise TypeError("qualification scope must be an EvidenceUseScope member")
        if any(not str(value).strip() for value in (self.revision, self.policy_version, self.sha256)):
            raise ValueError("qualification fields must be non-blank")


@dataclass(frozen=True, slots=True)
class TextDecision:
    """What the free-text step adds after the deterministic floor.

    Attributes:
        effect: ``allow``, ``deny``, ``clamp``, or ``down``.
        reason: Operator text for a deny. Empty when the ceiling copy is enough.
        applied_quantity: Quantity after a clamp. ``0`` on deny or Down.
        evidence: Log tokens. Free text is not included.
    """

    effect: str
    reason: str
    applied_quantity: int
    evidence: tuple[tuple[str, str], ...]


def load_policy() -> LayaPolicy:
    """Load the shipped policy file."""
    try:
        text = (files("flinttrade_engine") / "laya_policy.toml").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, TypeError, ModuleNotFoundError):
        text = Path(__file__).with_name("laya_policy.toml").read_text(encoding="utf-8")
    return parse_policy(text)


def parse_policy(text: str) -> LayaPolicy:
    """Parse a policy document.

    Raises:
        ValueError: The document is missing a pin or a threshold is not on a probability.
    """
    raw = tomllib.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Laya policy must be a table")
    version = str(raw.get("version") or "").strip()
    checkpoint = raw.get("checkpoint")
    questions = raw.get("question")
    if not version or not isinstance(checkpoint, dict) or not isinstance(questions, dict):
        raise ValueError("Laya policy is missing its version, checkpoint, or questions")
    _reject_confidence_key(raw)
    rules: list[QuestionRule] = []
    for question_id in _QUESTION_ORDER:
        spec = questions.get(question_id)
        if not isinstance(spec, dict):
            raise ValueError(f"Laya policy is missing question {question_id}")
        deny_option = str(spec.get("deny_option") or "")
        if deny_option not in _NEUTRAL_KEYS:
            raise ValueError("Laya policy deny options must be neutral A or B keys")
        deny_at = _unit_probability(spec.get("deny_at"), "deny_at")
        abstain_at = _unit_probability(spec.get("abstain_at"), "abstain_at")
        if abstain_at >= deny_at:
            raise ValueError("Laya abstain threshold must sit below the deny threshold")
        rules.append(
            QuestionRule(
                question_id=question_id,
                deny_option=deny_option,
                deny_at=deny_at,
                abstain_at=abstain_at,
            )
        )
    revision = str(checkpoint.get("revision") or "").strip()
    sha256 = str(checkpoint.get("sha256") or "").strip().lower()
    repo = str(checkpoint.get("repo") or "").strip()
    name = str(checkpoint.get("checkpoint") or "").strip()
    weight_file = str(checkpoint.get("file") or "").strip()
    if not all((revision, sha256, repo, name, weight_file)):
        raise ValueError("Laya policy checkpoint pin is incomplete")
    if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
        raise ValueError("Laya policy digest must be 64 lower-case hex characters")
    return LayaPolicy(
        version=version,
        repo=repo,
        revision=revision,
        checkpoint=name,
        weight_file=weight_file,
        sha256=sha256,
        questions=tuple(rules),
    )


def qualification_covers_live(record: LayaQualification | None, policy: LayaPolicy) -> bool:
    """Return whether ``record`` opens Live for this exact pin."""
    if record is None or type(record) is not LayaQualification:
        return False
    return (
        record.scope is EvidenceUseScope.LIVE_DECISION
        and record.revision == policy.revision
        and record.policy_version == policy.version
        and record.sha256 == policy.sha256
    )


def questions_for_note() -> dict[str, dict[str, object]]:
    """Return the neutral A/B questions. Facts the floor already knows are absent."""
    return {
        "rationale": {
            "type": "choice",
            "instructions": "Does the note state a concrete reason for the order?",
            "criteria": {
                "A": "a concrete reason is stated",
                "B": "no concrete reason is stated",
            },
        },
        "tilt": {
            "type": "choice",
            "instructions": "Does the note show tilt, revenge, or chasing losses?",
            "criteria": {
                "A": "tilt, revenge, or chasing losses",
                "B": "no tilt, revenge, or chasing losses",
            },
        },
        "side": {
            "type": "choice",
            "instructions": "Does the stated plan contradict the order side named in the note?",
            "criteria": {
                "A": "the stated plan contradicts the order side",
                "B": "the stated plan does not contradict the order side",
            },
        },
    }


def state_for_note(*, action: str, rationale: str) -> str:
    """Build the host state from the side label and the free text only."""
    side = action.strip().upper()
    return f"Order side: {side}\nNote:\n{rationale.strip()}"


def evaluate_free_text(
    *,
    mode: str,
    action: str,
    rationale: str,
    requested_quantity: int,
    degraded_ceiling: int,
    client: Any,
    policy: LayaPolicy | None = None,
) -> TextDecision:
    """Score free text. An empty note is uncertain and does not call the host.

    Uncertain answers, including an empty note, clamp in Practice and deny in
    Live. A host failure is Down.
    """
    active = policy or load_policy()
    note = rationale.strip()
    if not note:
        return _uncertain_decision(active, mode, requested_quantity, degraded_ceiling, "note_absent")
    if len(note) > _MAX_NOTE_CHARS:
        return TextDecision(
            effect="deny",
            reason="The note is too long to admit.",
            applied_quantity=0,
            evidence=(("policy_version", active.version), ("failure", "note_too_long")),
        )
    try:
        payload = client.decide(state_for_note(action=action, rationale=note), questions_for_note())
        effects = _effects_from_payload(payload, active)
    except DecisionCallError as exc:
        return _down_decision(active, exc.code)
    except Exception:
        return _down_decision(active, "malformed")
    evidence: list[tuple[str, str]] = [("policy_version", active.version), ("revision", active.revision)]
    evidence.extend(effects)
    deny = next((item for item in effects if item[0].endswith(":effect") and item[1] == "deny"), None)
    if deny is not None:
        question_id = deny[0].split(":", 1)[0]
        return TextDecision(
            effect="deny",
            reason=_deny_reason(question_id),
            applied_quantity=0,
            evidence=tuple(evidence),
        )
    abstain = any(item[1] == "abstain" for item in effects if item[0].endswith(":effect"))
    if abstain:
        decision = _uncertain_decision(active, mode, requested_quantity, degraded_ceiling, "abstain")
        return TextDecision(
            effect=decision.effect,
            reason=decision.reason,
            applied_quantity=decision.applied_quantity,
            evidence=tuple(evidence),
        )
    return TextDecision(
        effect="allow",
        reason="",
        applied_quantity=requested_quantity,
        evidence=tuple(evidence),
    )


def interpret_health(
    payload: Mapping[str, Any] | None,
    *,
    policy: LayaPolicy | None = None,
    requested_device: str = "cpu",
) -> DecisionStatus:
    """Map a sidecar health document to Ready, Degraded, or Down.

    A missing document, a missing digest, a revision mismatch, or a digest
    mismatch is Down.
    CPU fallback when a non-CPU device was requested is Degraded.
    """
    active = policy or load_policy()
    if not isinstance(payload, Mapping):
        return DecisionStatus.DOWN
    if str(payload.get("status") or "") != "ok":
        return DecisionStatus.DOWN
    loaded = payload.get("loaded")
    if not isinstance(loaded, (list, tuple)) or active.checkpoint not in loaded:
        return DecisionStatus.DOWN
    revisions = payload.get("revisions")
    if not isinstance(revisions, Mapping):
        return DecisionStatus.DOWN
    if str(revisions.get(active.checkpoint) or "") != active.revision:
        return DecisionStatus.DOWN
    reported = _reported_digest(payload, active)
    if reported is None or reported != active.sha256:
        return DecisionStatus.DOWN
    device = str(payload.get("device") or "")
    fallback_count = _fallback_count(payload, active.checkpoint)
    if requested_device == "cpu":
        if device not in {"", "cpu"}:
            return DecisionStatus.DOWN
        if fallback_count > 0:
            return DecisionStatus.DEGRADED
        return DecisionStatus.READY
    if device == "cpu" or fallback_count > 0:
        return DecisionStatus.DEGRADED
    if device == requested_device:
        return DecisionStatus.READY
    return DecisionStatus.DOWN


def health_identity_failure(
    payload: Mapping[str, Any] | None,
    *,
    policy: LayaPolicy | None = None,
    requested_device: str = "cpu",
) -> bool:
    """True when a Laya-shaped health document disagrees with the pin.

    A missing document, or one that has not finished loading, is not this
    failure. A loaded checkpoint with the wrong revision, a missing digest,
    or the wrong digest is. A device mismatch is Down without this flag.
    """
    if not isinstance(payload, Mapping):
        return False
    if str(payload.get("status") or "") != "ok":
        return False
    active = policy or load_policy()
    loaded = payload.get("loaded")
    revisions = payload.get("revisions")
    claims_model = (
        (isinstance(loaded, (list, tuple)) and active.checkpoint in loaded)
        or isinstance(revisions, Mapping)
        or "sha256" in payload
        or "digests" in payload
    )
    if not claims_model:
        return False
    if interpret_health(payload, policy=active, requested_device=requested_device) is not DecisionStatus.DOWN:
        return False
    if not isinstance(revisions, Mapping) or str(revisions.get(active.checkpoint) or "") != active.revision:
        return True
    reported = _reported_digest(payload, active)
    return reported is None or reported != active.sha256


def publish_probe(
    engine: Any,
    payload: Mapping[str, Any] | None,
    *,
    requested_device: str = "cpu",
    policy: LayaPolicy | None = None,
) -> DecisionStatus:
    """Record probe status. Live stays Down without a matching qualification record."""
    active = policy or load_policy()
    status = interpret_health(payload, policy=active, requested_device=requested_device)
    record = getattr(engine, "qualification", None)
    live = status is not DecisionStatus.DOWN and qualification_covers_live(record, active)
    engine.apply_runtime_status(status, live_qualified=live)
    return status


class SystemOneClient:
    """Small HTTP client for ``POST /v1/systemone``.

    The host is configurable so a managed sidecar and an operator endpoint
    share one caller. There is no third-party decision SDK.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "",
        timeout: float = 3.0,
        expected_revision: str,
        expected_sha256: str,
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        self._api_key = api_key.strip()
        if timeout <= 0:
            raise ValueError("decision timeout must be positive")
        self._timeout = timeout
        self._expected_revision = expected_revision.strip()
        self._expected_sha256 = expected_sha256.strip().lower()
        if not self._expected_revision or not self._expected_sha256:
            raise ValueError("decision client requires a revision and digest pin")

    @property
    def base_url(self) -> str:
        """Normalised host, without a trailing secret."""
        return self._base_url

    def decide(self, state: str, questions: Mapping[str, Mapping[str, object]]) -> Mapping[str, Any]:
        """Post one decision and return the decoded object.

        Raises:
            DecisionCallError: The host was unreachable, slow, or not usable.
        """
        url = f"{self._base_url}/v1/systemone"
        body = json.dumps({"state": state, "questions": questions, "model": "english"}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        if self._api_key:
            request.add_header("Authorization", f"Bearer {self._api_key}")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                status = getattr(response, "status", 200)
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise DecisionCallError(f"http_{exc.code}") from exc
        except TimeoutError as exc:
            raise DecisionCallError("timeout") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise DecisionCallError("timeout") from exc
            raise DecisionCallError("connection") from exc
        except OSError as exc:
            raise DecisionCallError("connection") from exc
        if status != 200:
            raise DecisionCallError(f"http_{status}")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise DecisionCallError("malformed")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DecisionCallError("malformed") from exc
        if not isinstance(payload, dict):
            raise DecisionCallError("malformed")
        self._check_identity(payload)
        return payload

    def _check_identity(self, payload: Mapping[str, Any]) -> None:
        """Reject a response whose revision or digest is not the pinned string.

        Missing, blank, padded, and non-string values are not the pin. That
        is Down.
        """
        if payload.get("revision") != self._expected_revision:
            raise DecisionCallError("revision_mismatch")
        if payload.get("sha256") != self._expected_sha256:
            raise DecisionCallError("digest_mismatch")


def _validate_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.hostname == "0.0.0.0"
    ):
        raise ValueError("decision host must be an http(s) origin")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{parsed.hostname}{port}"


def _reject_confidence_key(node: object) -> None:
    if isinstance(node, dict):
        if "confidence" in node:
            raise ValueError("Laya policy must not threshold the confidence field")
        for value in node.values():
            _reject_confidence_key(value)
    elif isinstance(node, list):
        for value in node:
            _reject_confidence_key(value)


def _unit_probability(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Laya policy {label} must be a probability")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > 1:
        raise ValueError(f"Laya policy {label} must be a probability")
    return number


def _effects_from_payload(payload: Mapping[str, Any], policy: LayaPolicy) -> list[tuple[str, str]]:
    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        raise DecisionCallError("malformed")
    effects: list[tuple[str, str]] = []
    for rule in policy.questions:
        answer = answers.get(rule.question_id)
        if not isinstance(answer, Mapping):
            raise DecisionCallError("missing_answer")
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, Mapping):
            raise DecisionCallError("malformed")
        deny_p = _probability(probabilities.get(rule.deny_option))
        other = "A" if rule.deny_option == "B" else "B"
        _probability(probabilities.get(other))
        if deny_p >= rule.deny_at:
            effect = "deny"
        elif deny_p >= rule.abstain_at:
            effect = "abstain"
        else:
            effect = "allow"
        effects.append((f"{rule.question_id}:effect", effect))
        effects.append((f"{rule.question_id}:p", f"{deny_p:.4f}"))
    return effects


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionCallError("malformed")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise DecisionCallError("malformed")
    return number


def _uncertain_decision(
    policy: LayaPolicy,
    mode: str,
    requested_quantity: int,
    degraded_ceiling: int,
    token: str,
) -> TextDecision:
    """Practice clamps. Live denies. The host is not required for this outcome."""
    evidence = (("policy_version", policy.version), ("rationale:effect", "abstain"), ("failure", token))
    if mode.strip().lower() == "live":
        return TextDecision(
            effect="deny",
            reason="Laya is uncertain. Live stays closed.",
            applied_quantity=0,
            evidence=evidence,
        )
    return TextDecision(
        effect="clamp",
        reason="Laya is uncertain. Quantity stays inside the tighter limit.",
        applied_quantity=min(requested_quantity, degraded_ceiling),
        evidence=evidence,
    )


def _down_decision(policy: LayaPolicy, code: str) -> TextDecision:
    return TextDecision(
        effect="down",
        reason="",
        applied_quantity=0,
        evidence=(("policy_version", policy.version), ("failure", code)),
    )


def _deny_reason(question_id: str) -> str:
    if question_id == "rationale":
        return "Laya denied this order. The note does not state a concrete reason."
    if question_id == "tilt":
        return "Laya denied this order. The note shows tilt or revenge."
    return "Laya denied this order. The stated plan contradicts the order side."


def _reported_digest(payload: Mapping[str, Any], policy: LayaPolicy) -> str | None:
    direct = payload.get("sha256")
    if isinstance(direct, str) and direct.strip():
        return direct.strip().lower()
    digests = payload.get("digests")
    if isinstance(digests, Mapping):
        for key in (policy.weight_file, policy.checkpoint):
            value = digests.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()
    return None


def _fallback_count(payload: Mapping[str, Any], checkpoint: str) -> int:
    fallbacks = payload.get("cpu_fallbacks")
    if not isinstance(fallbacks, Mapping):
        return 0
    bucket = fallbacks.get(checkpoint)
    if not isinstance(bucket, Mapping):
        return 0
    raw = bucket.get("count")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return max(0, raw)
