"""Ollama-backed Laya decision client.

Selected only when ``FLINTTRADE_LAYA_BACKEND`` is ``ollama``. The sidecar
client is a different type and stays in use for every other value except an
unrecognised one, which pauses new orders.

An allowlist entry is a tag, a pinned digest, and a route. ``chat`` calls
``/api/chat`` with a strict JSON schema. ``systemone`` calls ``/v1/systemone``
and maps choice or noul probabilities onto the existing thresholds. The
``confidence`` field is never a gate. Advisory chat is not this client.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from flinttrade_engine.laya import (
    LAYA_DOWN_REASON,
    LAYA_REASON_CODES,
    LAYA_REASON_DOWNLOAD_FAILED,
    LAYA_REASON_DOWNLOADING,
    LAYA_REASON_NOT_STARTED,
    LAYA_REASON_PORT_IN_USE,
    LAYA_REASON_STOPPED,
    LAYA_REASON_UNREACHABLE,
    LAYA_REASON_UNVERIFIED,
    LAYA_REASON_WRONG_REVISION,
    LAYA_START_COMMAND,
    DecisionStatus,
    laya_reason_detail,
    laya_reason_tooltip,
)
from flinttrade_engine.laya_decision import DecisionCallError, load_policy

_LOG = logging.getLogger("flinttrade.engine.laya_ollama")

BACKEND_ENV = "FLINTTRADE_LAYA_BACKEND"
MODEL_ENV = "FLINTTRADE_LAYA_OLLAMA_MODEL"
PROMPT_TOKEN_CAP = 8_192
DECISION_TIMEOUT_SECONDS = 3.0
# Stored only so a reason code has a legal port when the runtime has not bound one.
# Port-in-use copy is not shown unless the snapshot carried a real port.
_UNBOUND_PORT = 11434
_MAX_RESPONSE_BYTES = 1_000_000
_QUESTION_IDS = ("rationale", "tilt", "side")
_CHAT_OPTIONS = {"temperature": 0, "seed": 0, "num_predict": 256, "num_ctx": PROMPT_TOKEN_CAP}
_CHAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answers": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                question_id: {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "probabilities": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {"A": {"type": "number"}, "B": {"type": "number"}},
                            "required": ["A", "B"],
                        }
                    },
                    "required": ["probabilities"],
                }
                for question_id in _QUESTION_IDS
            },
            "required": list(_QUESTION_IDS),
        }
    },
    "required": ["answers"],
}

_unknown_logged = False
_session_override: Callable[[str], Any] | None = None
_poster_override: Callable[[str, str, Mapping[str, Any], float], Any] | None = None
_snapshot_override: Callable[[str], Mapping[str, Any] | None] | None = None


@dataclass(frozen=True, slots=True)
class LayaOllamaModel:
    """One reviewed gate model. The digest is the pin. The tag is not.

    Do not add an entry without a confirmed licence. ``tev1`` stays off this
    tuple while its fine-tuned weight licence is still being finalised
    upstream. ``nimble`` stays off until its Hugging Face licence card has
    been checked.
    """

    tag: str
    digest: str
    route: str

    def __post_init__(self) -> None:
        if self.route not in {"chat", "systemone"}:
            raise ValueError("Laya Ollama route must be chat or systemone")
        if _normalise_digest(self.digest) != self.digest:
            raise ValueError("Laya Ollama digest must be 64 lower-case hex characters")
        if not self.tag or any(char.isspace() for char in self.tag):
            raise ValueError("Laya Ollama model tag is invalid")


# Empty until a digest is reviewed. A tag alone never admits.
LAYA_OLLAMA_ALLOWLIST: tuple[LayaOllamaModel, ...] = ()


@dataclass(frozen=True, slots=True)
class LayaOllamaSurface:
    """Chip inputs already used by the desk. ``checking`` is the unconfirmed window."""

    status: DecisionStatus
    reason: str | None
    progress: tuple[int, int] | None
    checking: bool
    port: int


def laya_backend() -> str:
    """Return ``sidecar``, ``ollama``, or ``closed``.

    Unset, blank, and ``sidecar`` keep the sidecar and do not log. ``ollama``
    selects this module. Anything else is ``closed``: an unrecognised backend
    is an error, and an error must not admit. Falling back to the sidecar
    would keep placing after a typo.
    """
    global _unknown_logged
    raw = os.environ.get(BACKEND_ENV, "")
    value = raw.strip().lower()
    if value in {"", "sidecar"}:
        return "sidecar"
    if value == "ollama":
        return "ollama"
    if not _unknown_logged:
        shown = raw.replace("\n", " ").replace("\r", " ")[:64]
        _LOG.warning(
            "FLINTTRADE_LAYA_BACKEND=%r is not sidecar or ollama; new orders stay paused",
            shown,
        )
        _unknown_logged = True
    return "closed"


def reset_laya_backend_warning_for_tests() -> None:
    """Allow the unknown-backend warning to log again."""
    global _unknown_logged
    _unknown_logged = False


def set_laya_ollama_transport_for_tests(
    *,
    session: Callable[[str], Any] | None,
    poster: Callable[[str, str, Mapping[str, Any], float], Any] | None,
    snapshot: Callable[[str], Mapping[str, Any] | None] | None = None,
) -> None:
    """Replace the admission, HTTP call, and chip snapshot. Production leaves them unset."""
    global _session_override, _poster_override, _snapshot_override
    _session_override = session
    _poster_override = poster
    _snapshot_override = snapshot


def reset_laya_ollama_transport_for_tests() -> None:
    """Restore the managed runtime session, poster, and snapshot."""
    global _session_override, _poster_override, _snapshot_override
    _session_override = None
    _poster_override = None
    _snapshot_override = None


def estimate_tokens(text: str) -> int:
    """Estimate tokens as UTF-8 bytes divided by four.

    This is not the model tokenizer. Over this estimate, the order is refused
    the same way as a note that is too long.
    """
    size = len(text.encode("utf-8"))
    if size <= 0:
        return 0
    return (size + 3) // 4


# Status-menu detail only. The chip stays "Wrong model version".
OLLAMA_DIGEST_DETAIL = (
    "FlintTrade checks the digest Ollama reports for the exact model tag on every admission. "
    "The tag is not the proof. If that digest does not match the pinned digest, the gate shows "
    "Wrong model version and new orders stay paused. You can still close positions."
)
OLLAMA_NOT_STARTED_MANAGED = "Ollama isn't running. Start it to bring Laya back."
OLLAMA_NOT_STARTED_UNMANAGED = "Ollama isn't running. Start Ollama on this computer, then try again."
OLLAMA_START_ACTION = "Start Laya"
OLLAMA_STARTING_ACTION = "Starting…"
OLLAMA_START_FAILED = "Laya could not be started."
_OLLAMA_CHECKING_DETAIL = "Checking Laya…"


def ollama_chip_text(
    reason: str | None,
    port: int,
    *,
    progress: tuple[int, int] | None = None,
) -> str | None:
    """Chip words on the Ollama route. The same sentence the sidecar chip uses."""
    return laya_reason_detail(reason, port, progress=progress)


def ollama_not_started_line(*, managed: bool) -> str:
    """Next line when Ollama is not running. A managed install can be started."""
    if managed:
        return OLLAMA_NOT_STARTED_MANAGED
    return OLLAMA_NOT_STARTED_UNMANAGED


def ollama_status_menu_detail(reason: str | None, *, managed: bool) -> str | None:
    """Status-menu detail. The chip does not use these sentences."""
    if reason == LAYA_REASON_WRONG_REVISION:
        return OLLAMA_DIGEST_DETAIL
    if reason == LAYA_REASON_NOT_STARTED:
        return ollama_not_started_line(managed=managed)
    return None


def ollama_route_tooltip(reason: str | None, port: int, *, managed: bool) -> str | None:
    """Hover text on the Ollama route. It never names the sidecar start command."""
    if reason == LAYA_REASON_NOT_STARTED:
        return ollama_not_started_line(managed=managed)
    tooltip = laya_reason_tooltip(reason, port)
    if tooltip and LAYA_START_COMMAND in tooltip:
        return ollama_chip_text(reason, port)
    return tooltip


def ollama_route_visible_lines(*, managed: bool) -> tuple[str, ...]:
    """Every sentence the Ollama route can show. None of them say sidecar."""
    lines: list[str] = []
    for reason in sorted(LAYA_REASON_CODES):
        chip = ollama_chip_text(
            reason,
            11434,
            progress=(1_200_000_000, 3_400_000_000) if reason == LAYA_REASON_DOWNLOADING else None,
        )
        if chip:
            lines.append(chip)
        detail = ollama_status_menu_detail(reason, managed=managed)
        if detail:
            lines.append(detail)
        tooltip = ollama_route_tooltip(reason, 11434, managed=managed)
        if tooltip and tooltip not in {chip, detail}:
            lines.append(tooltip)
    lines.append(_OLLAMA_CHECKING_DETAIL)
    lines.append(LAYA_DOWN_REASON)
    lines.append(OLLAMA_START_FAILED)
    if managed:
        lines.append(OLLAMA_START_ACTION)
        lines.append(OLLAMA_STARTING_ACTION)
    for label in ("Ready", "Degraded", "Down", "Still loading", "Checking"):
        lines.append(f"Laya {label}")
    return tuple(lines)


def allowlist_entry(tag: str) -> LayaOllamaModel | None:
    """Return the reviewed entry for ``tag``, or ``None`` when it is absent."""
    wanted = tag.strip()
    for entry in LAYA_OLLAMA_ALLOWLIST:
        if entry.tag == wanted:
            return entry
    return None


def surface_from_ollama_snapshot(
    snapshot: Mapping[str, Any] | None,
    *,
    tag: str,
    entry: LayaOllamaModel | None,
) -> LayaOllamaSurface:
    """Map one runtime snapshot onto the existing chip vocabulary."""
    port, port_known = _ports(snapshot)
    if snapshot is None:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_NOT_STARTED, None, False, port)
    state = str(snapshot.get("state") or "")
    if state == "starting":
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_NOT_STARTED, None, True, port)
    pull = snapshot.get("model_pull")
    if isinstance(pull, Mapping) and _name_matches(str(pull.get("model") or ""), tag):
        pull_surface = _surface_for_pull(pull, port)
        if pull_surface is not None:
            return pull_surface
    if _drift_matches(snapshot.get("model_digest_drift"), tag):
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_WRONG_REVISION, None, False, port)
    if state in {"downloading", "extracting"}:
        return LayaOllamaSurface(
            DecisionStatus.DOWN,
            LAYA_REASON_DOWNLOADING,
            (_byte(snapshot.get("downloaded_bytes")), _byte(snapshot.get("download_total_bytes"))),
            False,
            port,
        )
    if state == "failed":
        if snapshot.get("integrity_error"):
            return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, port)
        error = str(snapshot.get("error") or "").lower()
        reason = LAYA_REASON_DOWNLOAD_FAILED if "download" in error else LAYA_REASON_UNREACHABLE
        return LayaOllamaSurface(DecisionStatus.DOWN, reason, None, False, port)
    if state == "conflict":
        reason = LAYA_REASON_PORT_IN_USE if port_known else LAYA_REASON_UNREACHABLE
        return LayaOllamaSurface(DecisionStatus.DOWN, reason, None, False, port)
    if not snapshot.get("ready"):
        reason = LAYA_REASON_STOPPED if state == "stopped" else LAYA_REASON_NOT_STARTED
        return LayaOllamaSurface(DecisionStatus.DOWN, reason, None, False, port)
    if entry is None:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, port)
    version = str(snapshot.get("pinned_server_version") or "")
    if entry.route == "systemone" and not version_at_least(version, 0, 35):
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, port)
    if not snapshot.get("model_present"):
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_DOWNLOADING, (0, 0), False, port)
    reported = _normalise_digest(snapshot.get("reported_digest"))
    if reported is None:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, port)
    if reported != entry.digest:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_WRONG_REVISION, None, False, port)
    return LayaOllamaSurface(DecisionStatus.READY, None, None, False, port)


def version_at_least(version: str, major: int, minor: int) -> bool:
    """Return whether ``version`` is at least ``major.minor``. A blank version is not."""
    text = version.strip().lstrip("v")
    parts = text.split(".")
    try:
        found = (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return False
    return found >= (major, minor)


def publish_ollama_gate_status(engine: Any | None = None) -> LayaOllamaSurface:
    """Record the Ollama chip on ``engine``. Errors pause new orders."""
    from flinttrade_engine.laya import process_laya  # noqa: PLC0415

    target = engine if engine is not None else process_laya()
    try:
        return _publish_ollama_gate_status(target)
    except Exception:
        _LOG.exception("Ollama Laya status could not be read")
        surface = LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, _UNBOUND_PORT)
        apply_ollama_surface(target, surface)
        return surface


def bind_ollama_gate(engine: Any) -> OllamaDecisionClient | None:
    """Publish the chip and return a client only when that chip is Ready."""
    surface = publish_ollama_gate_status(engine)
    if surface.status is not DecisionStatus.READY:
        return None
    tag = os.environ.get(MODEL_ENV, "").strip()
    entry = allowlist_entry(tag)
    if entry is None:
        return None
    snapshot = _load_snapshot(tag)
    version = str(snapshot.get("pinned_server_version") or "") if isinstance(snapshot, Mapping) else ""
    return OllamaDecisionClient(entry, server_version=version)


def apply_ollama_surface(engine: Any, surface: LayaOllamaSurface) -> None:
    """Write one surface onto the process gate. Live stays unqualified."""
    engine.set_gate_checking(surface.checking)
    if surface.status is DecisionStatus.DOWN:
        engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        progress = surface.progress if surface.reason == LAYA_REASON_DOWNLOADING else None
        engine.set_runtime_reason(surface.reason, surface.port, progress=progress)
        return
    engine.apply_runtime_status(DecisionStatus.READY, live_qualified=False)
    engine.set_runtime_reason(None, surface.port)
    engine.set_gate_checking(False)


class OllamaDecisionClient:
    """One admission, one call, digest checked before the body is trusted.

    ``last_proof`` is ``runtime`` when the admission digest matched the pin.
    The response body does not carry that proof.
    """

    def __init__(
        self,
        entry: LayaOllamaModel,
        *,
        timeout: float = DECISION_TIMEOUT_SECONDS,
        server_version: str = "",
    ) -> None:
        if timeout <= 0:
            raise ValueError("decision timeout must be positive")
        self._entry = entry
        self._timeout = timeout
        self._server_version = server_version.strip()
        self._last_proof = ""

    @property
    def last_proof(self) -> str:
        """``runtime`` after a digest-matched admission. Empty when the call failed."""
        return self._last_proof

    def decide(self, state: str, questions: Mapping[str, Mapping[str, object]]) -> Mapping[str, Any]:
        """Ask the admitted model and return probabilities for the three questions.

        Raises:
            DecisionCallError: The runtime, digest, timeout, or body cannot be used.
        """
        self._last_proof = ""
        if set(questions) != set(_QUESTION_IDS):
            raise DecisionCallError("malformed")
        if self._entry.route == "systemone" and not version_at_least(self._server_version, 0, 35):
            raise DecisionCallError("runtime_too_old")
        try:
            with _open_session(self._entry.tag) as admission:
                _require_admission(admission, self._entry)
                payload, path = _request_for(self._entry.route, admission.model, state, questions)
                encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
                if estimate_tokens(encoded) > PROMPT_TOKEN_CAP:
                    raise DecisionCallError("prompt_over_cap")
                raw = _post(admission.base_url, path, payload, self._timeout)
                _reject_oversized_usage(raw)
                _reject_advisory_body(raw)
                normalised = normalise_decision_payload(raw, self._entry.route, deny_options=_deny_options())
        except DecisionCallError:
            raise
        except Exception as exc:
            raise DecisionCallError(_code_for_foreign(exc)) from exc
        self._last_proof = "runtime"
        return normalised


def normalise_decision_payload(
    raw: Any,
    route: str,
    *,
    deny_options: Mapping[str, str],
) -> dict[str, Any]:
    """Return ``answers`` with A/B probabilities only. ``confidence`` is dropped."""
    body = _payload_object(raw, route)
    answers = body.get("answers")
    if not isinstance(answers, Mapping):
        raise DecisionCallError("malformed")
    cleaned: dict[str, dict[str, dict[str, float]]] = {}
    for question_id in _QUESTION_IDS:
        answer = answers.get(question_id)
        if not isinstance(answer, Mapping):
            raise DecisionCallError("missing_answer")
        cleaned[question_id] = {
            "probabilities": _option_probabilities(answer, deny_options[question_id]),
        }
    return {"answers": cleaned}


def _publish_ollama_gate_status(engine: Any) -> LayaOllamaSurface:
    if laya_backend() == "closed":
        surface = LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_UNVERIFIED, None, False, _UNBOUND_PORT)
        apply_ollama_surface(engine, surface)
        return surface
    tag = os.environ.get(MODEL_ENV, "").strip()
    entry = allowlist_entry(tag) if tag else None
    snapshot = _load_snapshot(tag)
    surface = surface_from_ollama_snapshot(snapshot, tag=tag, entry=entry)
    apply_ollama_surface(engine, surface)
    return surface


def _load_snapshot(model: str) -> Mapping[str, Any] | None:
    if _snapshot_override is not None:
        snapshot = _snapshot_override(model)
        if snapshot is None or isinstance(snapshot, Mapping):
            return snapshot
        return None
    from flinttrade_core.ollama_runtime import managed_ollama_gate_snapshot  # noqa: PLC0415

    snapshot = managed_ollama_gate_snapshot(model)
    if snapshot is None or isinstance(snapshot, Mapping):
        return snapshot
    return None


@contextmanager
def _open_session(model: str) -> Iterator[Any]:
    if _session_override is not None:
        with _session_override(model) as admission:
            yield admission
        return
    from flinttrade_core.ollama_runtime import managed_ollama_session  # noqa: PLC0415

    with managed_ollama_session(model) as admission:
        yield admission


def _post(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
    if _poster_override is not None:
        return _poster_override(base_url, path, payload, timeout)
    return _post_loopback(base_url, path, payload, timeout)


def _post_loopback(base_url: str, path: str, payload: Mapping[str, Any], timeout: float) -> Any:
    if path not in {"/api/chat", "/v1/systemone"}:
        raise DecisionCallError("malformed")
    url = _loopback_url(base_url, path)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FlintTrade/LayaOllama",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
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
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionCallError("malformed") from exc
    return decoded


def _loopback_url(base_url: str, path: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise DecisionCallError("connection")
    return f"http://127.0.0.1:{parsed.port}{path}"


def _require_admission(admission: Any, entry: LayaOllamaModel) -> None:
    digest = _normalise_digest(getattr(admission, "digest", None))
    if digest is None:
        raise DecisionCallError("digest_absent")
    if digest != entry.digest:
        raise DecisionCallError("digest_mismatch")
    base_url = str(getattr(admission, "base_url", "") or "")
    model = str(getattr(admission, "model", "") or "")
    if not base_url or not model:
        raise DecisionCallError("runtime_down")


def _request_for(
    route: str,
    model: str,
    state: str,
    questions: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, Any], str]:
    if route == "chat":
        return (
            {
                "model": model,
                "stream": False,
                "format": _CHAT_SCHEMA,
                "options": dict(_CHAT_OPTIONS),
                "messages": _chat_messages(state, questions),
            },
            "/api/chat",
        )
    return (
        {"model": model, "state": state, "questions": questions},
        "/v1/systemone",
    )


def _chat_messages(state: str, questions: Mapping[str, Mapping[str, object]]) -> list[dict[str, str]]:
    lines = [
        "Score the note. Return only the JSON object.",
        "Each answer needs probabilities for A and B. Do not return a confidence field.",
    ]
    for question_id in _QUESTION_IDS:
        spec = questions[question_id]
        lines.append(f"{question_id}: {spec.get('instructions', '')}")
        criteria = spec.get("criteria")
        if isinstance(criteria, Mapping):
            for option in ("A", "B"):
                lines.append(f"{question_id} {option}: {criteria.get(option, '')}")
    return [
        {"role": "system", "content": "\n".join(str(line) for line in lines)},
        {"role": "user", "content": state},
    ]


def _payload_object(raw: Any, route: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise DecisionCallError("malformed")
    if route == "chat":
        message = raw.get("message")
        if not isinstance(message, Mapping):
            raise DecisionCallError("malformed")
        content = message.get("content")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                raise DecisionCallError("malformed") from exc
        elif isinstance(content, Mapping):
            parsed = content
        else:
            raise DecisionCallError("malformed")
        if not isinstance(parsed, Mapping):
            raise DecisionCallError("malformed")
        return parsed
    return raw


def _option_probabilities(answer: Mapping[str, Any], deny_option: str) -> dict[str, float]:
    """Map a choice or noul answer onto A/B probabilities. Ignore ``confidence``."""
    if "confidence" in answer and "probabilities" not in answer and "noul" not in answer:
        raise DecisionCallError("malformed")
    probabilities = answer.get("probabilities")
    if isinstance(probabilities, Mapping):
        if "confidence" in probabilities and set(probabilities) <= {"confidence"}:
            raise DecisionCallError("malformed")
        cleaned: dict[str, float] = {}
        for option in ("A", "B"):
            if option not in probabilities:
                raise DecisionCallError("malformed")
            cleaned[option] = _unit(probabilities.get(option))
        return cleaned
    if "noul" not in answer:
        raise DecisionCallError("malformed")
    noul = _unit(answer.get("noul"))
    other = "A" if deny_option == "B" else "B"
    return {deny_option: noul, other: 1.0 - noul}


def _unit(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionCallError("malformed")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        raise DecisionCallError("malformed")
    return number


def _reject_advisory_body(raw: Any) -> None:
    """A chat-completion envelope is the advisory path. It is not a verdict."""
    if isinstance(raw, Mapping) and "choices" in raw:
        raise DecisionCallError("malformed")


def _reject_oversized_usage(raw: Any) -> None:
    if not isinstance(raw, Mapping):
        return
    counts = [raw.get("prompt_eval_count")]
    usage = raw.get("usage")
    if isinstance(usage, Mapping):
        counts.append(usage.get("input_tokens"))
    for count in counts:
        if isinstance(count, bool) or not isinstance(count, int):
            continue
        if count > PROMPT_TOKEN_CAP:
            raise DecisionCallError("prompt_over_cap")


def _deny_options() -> dict[str, str]:
    policy = load_policy()
    return {rule.question_id: rule.deny_option for rule in policy.questions}


def _code_for_foreign(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, TimeoutError):
        return "timeout"
    if "digest" in text:
        return "digest_mismatch"
    if "not accepted" in text:
        return "model_missing"
    if "not ready" in text or "not installed" in text or "changing state" in text:
        return "runtime_down"
    if type(exc).__name__ == "OllamaRuntimeError":
        return "runtime_down"
    return "malformed"


def _surface_for_pull(pull: Mapping[str, Any], port: int) -> LayaOllamaSurface | None:
    status = str(pull.get("status") or "")
    if status in {"failed", "cancelled"}:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_DOWNLOAD_FAILED, None, False, port)
    if status == "awaiting_digest_acceptance" or pull.get("digest_changed") is True:
        return LayaOllamaSurface(DecisionStatus.DOWN, LAYA_REASON_WRONG_REVISION, None, False, port)
    if status in {"success", "accepted"}:
        return None
    if status:
        return LayaOllamaSurface(
            DecisionStatus.DOWN,
            LAYA_REASON_DOWNLOADING,
            (_byte(pull.get("completed")), _byte(pull.get("total"))),
            False,
            port,
        )
    return None


def _drift_matches(drift: object, tag: str) -> bool:
    if not isinstance(drift, Mapping) or not tag:
        return False
    return any(_name_matches(str(name), tag) for name in drift)


def _name_matches(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return bool(_aliases(left) & _aliases(right))


def _aliases(name: str) -> set[str]:
    names = {name}
    tail = name.rsplit("/", 1)[-1]
    if tail.endswith(":latest"):
        names.add(name[: -len(":latest")])
    elif ":" not in tail:
        names.add(f"{name}:latest")
    return names


def _ports(snapshot: Mapping[str, Any] | None) -> tuple[int, bool]:
    if isinstance(snapshot, Mapping):
        port = snapshot.get("port")
        if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
            return port, True
    return _UNBOUND_PORT, False


def _byte(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _normalise_digest(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    text = text.removeprefix("sha256:")
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return None
    return text
