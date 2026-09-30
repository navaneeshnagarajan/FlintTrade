"""Offline harness for one Laya candidate.

The command calls the same free-text seam as the gate. It does not call
SafetySystem or the order gate. Vendor figures are not an input.

.. code-block:: bash

    python -m flinttrade_engine.laya_benchmark --cases PATH --split dev --repeats N
    python -m flinttrade_engine.laya_benchmark --cases PATH --split test --exclude IDS

``PATH`` is JSONL. Each line has ``id``, ``pair_id``, ``split`` (``dev`` or
``test``), ``question``, ``note``, ``order_context``, and ``label``
(``admit``, ``deny``, or ``clamp``). ``group``, ``difficulty``, ``path``, and
``why`` are reported when present. Unknown fields are ignored. Only
``order_context.side`` is sent to the model, through :func:`state_for_note`.
Quantity and mode stay on the deterministic floor.

Counts use the first repeat. Latency and stability use every repeat. With
zero wrong admits, ``n`` deny-labelled cases bound the true wrong-admit rate
at about ``3/n`` at 95%. The report prints that ``n``. A draft with 59 deny
cases cannot support a claim under 1%.

A wrong admit is a full allow when the label is ``deny`` or ``clamp``. A
wrong deny is a hard deny when the label is ``admit``. A deny-option
probability from ``abstain_at`` (0.55) up to but not including ``deny_at``
(0.80) is an abstain: a clamp in Practice and a deny in Live. Abstain is its
own count. The empty note and a note over 4,000 characters after stripping
are decided in code before any model call.

``--tune`` is refused unless ``--split dev``. Tuning does not edit
``laya_policy.toml``. Test is scored once. ``--stub`` is not a model score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flinttrade_engine.laya_decision import (
    DecisionCallError,
    TextDecision,
    evaluate_free_text,
    questions_for_note,
    state_for_note,
)

_QUESTIONS = ("rationale", "tilt", "side")
_QUESTION_SET = frozenset(_QUESTIONS)
_SPLITS = frozenset({"dev", "test"})
_LABELS = frozenset({"admit", "deny", "clamp"})
_GROUPS = ("core", "hinglish", "injection", "empty_note", "length")
_DIFFICULTIES = ("easy", "hard")
_DETERMINISTIC_FAILURES = frozenset({"note_absent", "note_too_long"})
LATENCY_BAR_MS = 3_000.0
_EXAMPLE_DIGEST = "ab" * 32
_DRILL_TAG = "example:bench"
_VENDOR_NOTE = (
    "note=If wrong admits are 0, n deny-labelled cases bound the true "
    "wrong-admit rate at about 3/n at 95%. A set whose 3/n is at least 0.01 "
    "cannot claim under 1%. Vendor numbers are unverified."
)


class BenchmarkCaseError(ValueError):
    """One JSONL line cannot be scored."""


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One labelled free-text case. The model sees ``side`` and ``note`` only."""

    id: str
    pair_id: str
    split: str
    question: str
    note: str
    side: str
    mode: str
    quantity: int
    label: str
    group: str
    difficulty: str
    path: str
    why: str


@dataclass(frozen=True, slots=True)
class QuestionTally:
    """Separate wrong-admit, wrong-deny, and abstain counts."""

    name: str
    n: int
    n_admit: int
    n_deny: int
    n_clamp: int
    wrong_admits: int
    wrong_denies: int
    abstains: int
    downs: int
    correct: int
    other: int


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """First-repeat band, plus every repeat's latency and stability key."""

    case: BenchmarkCase
    band: str
    signatures: tuple[str, ...]
    latencies_ms: tuple[float, ...]
    probs: str
    failure: str


@dataclass(frozen=True, slots=True)
class DrillResult:
    """One fail-closed drill. Closing a position stays allowed."""

    name: str
    ended: str
    close_allowed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Printed measurements. ``n`` is cases, not cases times repeats."""

    candidate: str
    split: str
    file_sha256: str
    repeats: int
    stub: bool
    tune_note: str
    test_scored_once: bool
    outcomes: tuple[CaseOutcome, ...]

    def render(self, exclude: frozenset[str] | None = None) -> str:
        """Return one block. ``exclude`` drops those ids from the tallies."""
        chosen = self.outcomes
        excluded_label = "no"
        if exclude:
            chosen = tuple(row for row in self.outcomes if row.case.id not in exclude)
            excluded_label = ",".join(sorted(exclude))
        lines = [
            f"candidate {self.candidate} repeats={self.repeats} stub={'yes' if self.stub else 'no'}",
            f"split={self.split} file_sha256={self.file_sha256} excluded={excluded_label}",
        ]
        if self.test_scored_once:
            lines.append("test_scored_once=yes")
        if self.tune_note:
            lines.append(self.tune_note)
        if self.stub:
            lines.append("model_score=no")
            lines.append("note=Stub results are not a model score.")
        by_question = [_tally(question, chosen) for question in _QUESTIONS]
        by_question.append(_tally("overall", chosen))
        lines.extend(_format_tally("question", tally) for tally in by_question)
        lines.extend(_format_tally("group", tally) for tally in _named_tallies(chosen, "group", _GROUPS))
        lines.extend(
            _format_tally("difficulty", tally) for tally in _named_tallies(chosen, "difficulty", _DIFFICULTIES)
        )
        latencies = [ms for row in chosen for ms in row.latencies_ms]
        p50 = percentile(latencies, 50)
        p95 = percentile(latencies, 95)
        within = "yes" if latencies and p95 <= LATENCY_BAR_MS else "no"
        lines.append(
            f"latency_p50_ms={p50:.3f} latency_p95_ms={p95:.3f} "
            f"latency_bar_ms={LATENCY_BAR_MS:.1f} latency_p95_within_bar={within}"
        )
        stable = sum(1 for row in chosen if len(set(row.signatures)) == 1)
        lines.append(f"stability stable={stable} unstable={len(chosen) - stable}")
        overall = by_question[-1]
        lines.append(f"n_deny={overall.n_deny}")
        if overall.wrong_admits == 0 and overall.n_deny > 0:
            lines.append(f"wrong_admit_95_upper=3/{overall.n_deny}")
        else:
            lines.append("wrong_admit_95_upper=undefined")
        lines.append(f"cannot_claim_under_1_percent={_cannot_claim(overall)}")
        for row in chosen:
            lines.append(
                f"case id={row.case.id} question={row.case.question} group={row.case.group} "
                f"difficulty={row.case.difficulty} label={row.case.label} band={row.band} "
                f"probs={row.probs} failure={row.failure}"
            )
        lines.append(_VENDOR_NOTE)
        return "\n".join(lines) + "\n"


def state_for_case(case: BenchmarkCase) -> str:
    """Return the host state. Symbol, quantity, and mode are not included."""
    return state_for_note(action=case.side, rationale=case.note)


def file_sha256(path: Path) -> str:
    """SHA-256 of the case file's exact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> tuple[BenchmarkCase, ...]:
    """Load JSONL cases. A bad line raises :class:`BenchmarkCaseError`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchmarkCaseError(f"could not read {path.name}") from exc
    cases: list[BenchmarkCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        cases.append(_parse_line(line, line_number))
    if not cases:
        raise BenchmarkCaseError("case file has no rows")
    return tuple(cases)


def load_exclude_ids(path: Path) -> frozenset[str]:
    """Load one id per line. Blank lines and ``#`` comments are ignored."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BenchmarkCaseError(f"could not read {path.name}") from exc
    ids: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(stripped)
    return frozenset(ids)


def select_split(cases: Sequence[BenchmarkCase], split: str | None) -> tuple[BenchmarkCase, ...]:
    """Keep one split. ``None`` keeps every row."""
    if split is None:
        return tuple(cases)
    if split not in _SPLITS:
        raise BenchmarkCaseError("split must be dev or test")
    selected = tuple(case for case in cases if case.split == split)
    if not selected:
        raise BenchmarkCaseError(f"no {split} rows")
    return selected


def run_benchmark(
    cases: Sequence[BenchmarkCase],
    client: Any,
    *,
    repeats: int = 1,
    candidate: str = "unspecified",
    split: str = "all",
    file_sha256_hex: str = "",
    stub: bool = False,
    tune_note: str = "",
    test_scored_once: bool = False,
) -> BenchmarkReport:
    """Score ``cases`` through :func:`evaluate_free_text`."""
    if repeats < 1:
        raise BenchmarkCaseError("repeats must be at least 1")
    outcomes: list[CaseOutcome] = []
    for case in cases:
        signatures: list[str] = []
        latencies: list[float] = []
        first: tuple[str, str, str] | None = None
        for _ in range(repeats):
            started = time.perf_counter()
            decision, probs, failure, signature = _score_case(case, client)
            latencies.append((time.perf_counter() - started) * 1000)
            signatures.append(signature)
            if first is None:
                first = (_band(case, decision), probs, failure)
        assert first is not None
        outcomes.append(
            CaseOutcome(
                case=case,
                band=first[0],
                signatures=tuple(signatures),
                latencies_ms=tuple(latencies),
                probs=first[1],
                failure=first[2],
            )
        )
    return BenchmarkReport(
        candidate=candidate,
        split=split,
        file_sha256=file_sha256_hex,
        repeats=repeats,
        stub=stub,
        tune_note=tune_note,
        test_scored_once=test_scored_once,
        outcomes=tuple(outcomes),
    )


def percentile(values: Sequence[float], percent: float) -> float:
    """Nearest-rank percentile. ``percent`` is 50 or 95."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil((percent / 100) * len(ordered)))
    return float(ordered[rank - 1])


def render_drills(results: Sequence[DrillResult]) -> str:
    """Format fail-closed drill rows. One line per drill."""
    lines = ["drills"]
    for drill in results:
        close = "yes" if drill.close_allowed else "no"
        lines.append(f"drill {drill.name} ended={drill.ended} close_allowed={close} detail={drill.detail}")
    return "\n".join(lines) + "\n"


def run_fail_closed_drills() -> tuple[DrillResult, ...]:
    """Each drill ends in Down or a refusal. Closing a position still admits.

    Transport, the allowlist, and the backend env are restored afterwards.
    No drill calls a live runtime.
    """
    import flinttrade_engine.laya_ollama as ollama_mod  # noqa: PLC0415
    from flinttrade_engine.laya import (  # noqa: PLC0415
        LAYA_DOWN_REASON,
        DecisionStatus,
        Laya,
        Proposal,
        laya_reason_detail,
    )
    from flinttrade_engine.laya_ollama import (  # noqa: PLC0415
        OllamaDecisionClient,
        reset_laya_ollama_transport_for_tests,
        set_laya_ollama_transport_for_tests,
    )

    saved_allowlist = ollama_mod.LAYA_OLLAMA_ALLOWLIST
    saved_backend = os.environ.get("FLINTTRADE_LAYA_BACKEND")
    saved_model = os.environ.get("FLINTTRADE_LAYA_OLLAMA_MODEL")
    calls: list[str] = []

    def restore() -> None:
        ollama_mod.LAYA_OLLAMA_ALLOWLIST = saved_allowlist
        reset_laya_ollama_transport_for_tests()
        _restore_env("FLINTTRADE_LAYA_BACKEND", saved_backend)
        _restore_env("FLINTTRADE_LAYA_OLLAMA_MODEL", saved_model)

    arm = set_laya_ollama_transport_for_tests
    try:
        return (
            _drill_stopped(Laya, Proposal, laya_reason_detail, DecisionStatus, arm, calls),
            _drill_missing_model(Laya, Proposal, laya_reason_detail, arm, calls),
            _drill_wrong_digest(Laya, Proposal, laya_reason_detail, arm, calls),
            _drill_timeout(Laya, Proposal, LAYA_DOWN_REASON, laya_reason_detail, arm, calls),
            _drill_malformed(Laya, Proposal, LAYA_DOWN_REASON, arm, calls),
            _drill_oversized(OllamaDecisionClient, Laya, Proposal, arm, calls),
            _drill_note_too_long(Laya, Proposal, arm, calls),
            _drill_empty_live(Laya, Proposal, arm, calls),
            _drill_runtime_too_old(Laya, Proposal, laya_reason_detail, arm, calls),
            _drill_advisory_choices(Laya, Proposal, LAYA_DOWN_REASON, arm, calls),
        )
    finally:
        restore()


def main(argv: list[str] | None = None) -> int:
    """Print a report. Exit 2 when the file is bad or tuning is aimed at test."""
    parser = argparse.ArgumentParser(description="Score a Laya candidate on labelled JSONL.")
    parser.add_argument("--cases", required=True, help="JSONL file of labelled cases")
    parser.add_argument("--repeats", type=int, default=1, help="Repeats of each case for stability")
    parser.add_argument("--model", default="", help="Candidate tag. Reported only.")
    parser.add_argument("--route", default="", help="chat or systemone. Reported only.")
    parser.add_argument("--split", choices=("dev", "test"), default=None, help="Score one split")
    parser.add_argument("--tune", action="store_true", help="Select thresholds. Refused unless --split dev")
    parser.add_argument("--exclude", default="", help="Optional file of case ids to report a second time")
    parser.add_argument("--stub", action="store_true", help="Allow-all client. Not a model score")
    parser.add_argument("--skip-drills", action="store_true", help="Omit the fail-closed drill section")
    args = parser.parse_args(argv)
    if args.tune and args.split != "dev":
        print("error=refusing to tune on test")
        return 2
    try:
        path = Path(args.cases)
        digest = file_sha256(path)
        cases = select_split(load_cases(path), args.split)
        exclude = load_exclude_ids(Path(args.exclude)) if args.exclude else frozenset()
        split_name = args.split or _split_name(cases)
        tune_note = "tune=not_applied thresholds_unchanged=yes" if args.tune else ""
        client = _StubAllowClient() if args.stub else _cli_client(args.model)
        report = run_benchmark(
            cases,
            client,
            repeats=args.repeats,
            candidate=_candidate_label(args.model, args.route),
            split=split_name,
            file_sha256_hex=digest,
            stub=args.stub,
            tune_note=tune_note,
            test_scored_once=args.split == "test",
        )
        drills = () if args.skip_drills else run_fail_closed_drills()
    except BenchmarkCaseError as exc:
        print(f"error={exc}")
        return 2
    print(report.render(), end="")
    if exclude:
        print(report.render(exclude), end="")
    if drills:
        print(render_drills(drills), end="")
    return 0


def _cli_client(model: str) -> Any:
    """Use an allowlisted Ollama client, or a client that always fails closed."""
    from flinttrade_engine.laya_ollama import (  # noqa: PLC0415
        OllamaDecisionClient,
        allowlist_entry,
    )

    entry = allowlist_entry(model) if model else None
    if entry is None:
        return _FailClosedClient()
    return OllamaDecisionClient(entry)


class _FailClosedClient:
    """No model call. The harness must not count this as an admit."""

    last_proof = ""

    def decide(self, state: str, questions: Mapping[str, Mapping[str, object]]) -> Mapping[str, Any]:
        del state, questions
        raise DecisionCallError("runtime_down")


class _StubAllowClient:
    """Every deny option is 0.1. Host deny labels become wrong admits."""

    last_proof = "runtime"

    def decide(self, state: str, questions: Mapping[str, Mapping[str, object]]) -> Mapping[str, Any]:
        del state, questions
        return _option_payload(0.1)


def _score_case(case: BenchmarkCase, client: Any) -> tuple[TextDecision, str, str, str]:
    capture = _Capture(client)
    decision = evaluate_free_text(
        mode=case.mode,
        action=case.side,
        rationale=case.note,
        requested_quantity=case.quantity,
        degraded_ceiling=1,
        client=capture,
    )
    failure = _failure_token(decision)
    probs = "none" if not capture.called else _format_probs(capture.payload)
    return decision, probs, failure, _signature(decision)


def _band(case: BenchmarkCase, decision: TextDecision) -> str:
    """Classify one decision. Abstain is not a wrong admit and not a wrong deny."""
    failure = _failure_token(decision)
    if failure in _DETERMINISTIC_FAILURES:
        return _band_deterministic(case.label, decision.effect)
    if decision.effect in {"down", "unverified"}:
        return "down"
    bands = _question_bands(decision)
    denies = [question for question, effect in bands.items() if effect == "deny"]
    if denies:
        if case.label == "admit":
            return "wrong_deny"
        if case.label == "deny" and case.question in denies:
            return "correct"
        return "other"
    if any(effect == "abstain" for effect in bands.values()):
        return "abstain"
    if len(bands) == len(_QUESTIONS) and all(effect == "allow" for effect in bands.values()):
        if case.label == "admit":
            return "correct"
        return "wrong_admit"
    return "other"


def _band_deterministic(label: str, effect: str) -> str:
    if effect == "allow" and label in {"deny", "clamp"}:
        return "wrong_admit"
    if effect == "deny" and label == "admit":
        return "wrong_deny"
    if effect == "allow" and label == "admit":
        return "correct"
    if effect == "deny" and label == "deny":
        return "correct"
    if effect == "clamp" and label == "clamp":
        return "correct"
    if effect in {"down", "unverified"}:
        return "down"
    return "other"


def _question_bands(decision: TextDecision) -> dict[str, str]:
    bands: dict[str, str] = {}
    for key, value in decision.evidence:
        if key.endswith(":effect"):
            question = key.split(":", 1)[0]
            if question in _QUESTION_SET and value in {"allow", "deny", "abstain"}:
                bands[question] = value
    return bands


def _failure_token(decision: TextDecision) -> str:
    for key, value in decision.evidence:
        if key == "failure":
            return value
    return "none"


def _signature(decision: TextDecision) -> str:
    """Stability key. Bands, not the raw probabilities."""
    failure = _failure_token(decision)
    if failure in _DETERMINISTIC_FAILURES:
        return f"deterministic:{decision.effect}"
    if decision.effect in {"down", "unverified"}:
        return "down"
    bands = _question_bands(decision)
    return ",".join(f"{question}={bands.get(question, 'missing')}" for question in _QUESTIONS)


def _format_probs(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return "none"
    answers = payload.get("answers")
    if not isinstance(answers, Mapping):
        return "none"
    parts: list[str] = []
    for question in _QUESTIONS:
        answer = answers.get(question)
        if not isinstance(answer, Mapping):
            return "none"
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, Mapping):
            return "none"
        rendered: list[str] = []
        for option in ("A", "B"):
            value = probabilities.get(option)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "none"
            rendered.append(f"{option}={format(float(value), '.12g')}")
        parts.append(f"{question}:{','.join(rendered)}")
    return ";".join(parts)


class _Capture:
    """Remember the payload and the state actually sent to ``decide``."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.payload: Mapping[str, Any] | None = None
        self.state: str | None = None
        self.called = False

    @property
    def last_proof(self) -> str:
        return str(getattr(self._inner, "last_proof", "") or "")

    def decide(self, state: str, questions: Mapping[str, Mapping[str, object]]) -> Mapping[str, Any]:
        self.called = True
        self.state = state
        payload = self._inner.decide(state, questions)
        self.payload = payload if isinstance(payload, Mapping) else None
        return payload


def _tally(name: str, rows: Sequence[CaseOutcome]) -> QuestionTally:
    selected = [row for row in rows if name == "overall" or row.case.question == name]
    return _tally_rows(name, selected)


def _named_tallies(rows: Sequence[CaseOutcome], field: str, canonical: Sequence[str]) -> tuple[QuestionTally, ...]:
    present = {str(getattr(row.case, field)) for row in rows}
    extras = sorted(name for name in present if name not in canonical)
    ordered = [*canonical, *extras]
    return tuple(
        _tally_rows(name, [row for row in rows if getattr(row.case, field) == name]) for name in ordered
    )


def _tally_rows(name: str, rows: Sequence[CaseOutcome]) -> QuestionTally:
    counts = {"wrong_admit": 0, "wrong_deny": 0, "abstain": 0, "down": 0, "correct": 0, "other": 0}
    n_admit = n_deny = n_clamp = 0
    for row in rows:
        if row.case.label == "admit":
            n_admit += 1
        elif row.case.label == "deny":
            n_deny += 1
        else:
            n_clamp += 1
        key = row.band if row.band in counts else "other"
        counts[key] += 1
    return QuestionTally(
        name=name,
        n=len(rows),
        n_admit=n_admit,
        n_deny=n_deny,
        n_clamp=n_clamp,
        wrong_admits=counts["wrong_admit"],
        wrong_denies=counts["wrong_deny"],
        abstains=counts["abstain"],
        downs=counts["down"],
        correct=counts["correct"],
        other=counts["other"],
    )


def _format_tally(prefix: str, tally: QuestionTally) -> str:
    return (
        f"{prefix} {tally.name} n={tally.n} "
        f"n_admit={tally.n_admit} n_deny={tally.n_deny} n_clamp={tally.n_clamp} "
        f"wrong_admits={tally.wrong_admits} wrong_denies={tally.wrong_denies} "
        f"abstains={tally.abstains} downs={tally.downs} "
        f"correct={tally.correct} other={tally.other}"
    )


def _cannot_claim(tally: QuestionTally) -> str:
    if tally.wrong_admits > 0 or tally.n_deny <= 0:
        return "yes"
    bound = 3 / tally.n_deny
    if bound >= 0.01 or tally.n_deny < 300:
        return "yes"
    return "no"


def _split_name(cases: Sequence[BenchmarkCase]) -> str:
    found = {case.split for case in cases}
    if len(found) == 1:
        return next(iter(found))
    return "all"


def _candidate_label(model: str, route: str) -> str:
    tag = model.strip() or "unset"
    selected = route.strip() or "unset"
    return f"tag={tag} route={selected}"


def _parse_line(line: str, line_number: int) -> BenchmarkCase:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise BenchmarkCaseError(f"line {line_number} is not JSON") from exc
    if not isinstance(raw, dict):
        raise BenchmarkCaseError(f"line {line_number} is not an object")
    identity = _required_text(raw.get("id"), line_number, "id")
    pair_id = _required_text(raw.get("pair_id"), line_number, "pair_id")
    split = _required_text(raw.get("split"), line_number, "split")
    question = _required_text(raw.get("question"), line_number, "question")
    label = _required_text(raw.get("label"), line_number, "label")
    note = raw.get("note")
    order = raw.get("order_context")
    if split not in _SPLITS or question not in _QUESTION_SET or label not in _LABELS:
        raise BenchmarkCaseError(f"line {line_number} has a bad split, question, or label")
    if not isinstance(note, str) or not isinstance(order, dict):
        raise BenchmarkCaseError(f"line {line_number} is missing note or order_context")
    side = str(order.get("side") or "").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise BenchmarkCaseError(f"line {line_number} order_context.side must be BUY or SELL")
    mode = str(order.get("mode") or "practice").strip().lower() or "practice"
    return BenchmarkCase(
        id=identity,
        pair_id=pair_id,
        split=split,
        question=question,
        note=note,
        side=side,
        mode=mode,
        quantity=_quantity(order.get("quantity")),
        label=label,
        group=_optional_text(raw.get("group")),
        difficulty=_optional_text(raw.get("difficulty")),
        path=_optional_text(raw.get("path"), default=""),
        why=_optional_text(raw.get("why"), default=""),
    )


def _required_text(value: object, line_number: int, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkCaseError(f"line {line_number} is missing {field}")
    return value.strip()


def _optional_text(value: object, default: str = "unset") -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value.strip()


def _quantity(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 20
    return value


def _option_payload(deny_p: float) -> dict[str, Any]:
    other = 1.0 - deny_p
    return {
        "answers": {
            "rationale": {"probabilities": {"A": other, "B": deny_p}},
            "tilt": {"probabilities": {"A": deny_p, "B": other}},
            "side": {"probabilities": {"A": deny_p, "B": other}},
        }
    }


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _ready_snapshot(digest: str, *, version: str = "0.35.0", present: bool = True) -> dict[str, Any]:
    return {
        "state": "ready",
        "ready": True,
        "model_present": present,
        "reported_digest": digest,
        "pinned_server_version": version,
        "port": 11435,
    }


@contextmanager
def _drill_transport(
    set_transport: Any,
    *,
    route: str,
    snapshot: Mapping[str, Any] | None,
    poster: Any,
    session_digest: str,
):
    import flinttrade_engine.laya_ollama as ollama_mod  # noqa: PLC0415
    from flinttrade_engine.laya_ollama import LayaOllamaModel  # noqa: PLC0415

    ollama_mod.LAYA_OLLAMA_ALLOWLIST = (
        LayaOllamaModel(tag=_DRILL_TAG, digest=_EXAMPLE_DIGEST, route=route),
    )
    os.environ["FLINTTRADE_LAYA_BACKEND"] = "ollama"
    os.environ["FLINTTRADE_LAYA_OLLAMA_MODEL"] = _DRILL_TAG

    @contextmanager
    def session(model: str):
        del model
        yield SimpleNamespace(
            digest=session_digest,
            base_url="http://127.0.0.1:11435",
            model=f"flinttrade/sha256-{session_digest}:locked",
        )

    set_transport(session=session, poster=poster, snapshot=lambda _model: snapshot)
    try:
        yield
    finally:
        set_transport(session=None, poster=None, snapshot=None)


def _proposal(proposal_type: Any, rationale: str, *, mode: str = "practice") -> Any:
    return proposal_type(
        symbol="EXAMPLE",
        exchange="NFO",
        action="BUY",
        quantity=20,
        mode=mode,
        rationale=rationale,
    )


def _close_allowed(engine: Any, proposal_type: Any) -> bool:
    verdict = engine.admit_reduce_only(_proposal(proposal_type, "Close the EXAMPLE long."))
    return bool(verdict.allow and verdict.applied_quantity == 20)


def _detail(engine: Any, laya_reason_detail: Any) -> str:
    reason, port = engine.runtime_reason()
    text = laya_reason_detail(reason, port, progress=engine.download_progress())
    return text or "none"


def _drill_stopped(laya_type, proposal_type, detail_fn, status_type, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("stopped")
        raise AssertionError("stopped runtime must not be called")

    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=None,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        engine = laya_type(status=status_type.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and len(calls) == before else "allow"
        detail = _detail(engine, detail_fn) if ended == "down" else "called"
        return DrillResult("ollama_stopped", ended, close, detail)


def _drill_missing_model(laya_type, proposal_type, detail_fn, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("missing")
        raise AssertionError("missing model must not be called")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST, present=False)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and len(calls) == before else "allow"
        return DrillResult("model_missing", ended, close, _detail(engine, detail_fn))


def _drill_wrong_digest(laya_type, proposal_type, detail_fn, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("digest")
        raise AssertionError("digest mismatch must not be posted")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest="cd" * 32,
    ):
        from flinttrade_engine.laya import LAYA_DOWN_REASON, DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        matched = not verdict.allow and verdict.reason == LAYA_DOWN_REASON and len(calls) == before
        ended = "down" if matched else "allow"
        return DrillResult("wrong_digest", ended, close, _detail(engine, detail_fn))


def _drill_timeout(laya_type, proposal_type, pause: str, detail_fn, set_transport, calls: list[str]) -> DrillResult:
    def poster(*_args: Any) -> Any:
        calls.append("timeout")
        raise TimeoutError("drill")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and verdict.reason == pause else "allow"
        return DrillResult("timeout", ended, close, _detail(engine, detail_fn))


def _drill_malformed(laya_type, proposal_type, pause: str, set_transport, calls: list[str]) -> DrillResult:
    def poster(*_args: Any) -> Any:
        calls.append("malformed")
        return {"message": {"content": "Sure"}}

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and verdict.reason == pause else "allow"
        return DrillResult("malformed_output", ended, close, "refusal" if ended == "down" else "allow")


def _drill_oversized(client_type, laya_type, proposal_type, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("oversized")
        raise AssertionError("over-cap prompt must not be posted")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415
        from flinttrade_engine.laya_ollama import allowlist_entry  # noqa: PLC0415

        entry = allowlist_entry(_DRILL_TAG)
        assert entry is not None
        client = client_type(entry, server_version="0.35.0")
        try:
            client.decide("x" * 40_000, questions_for_note())
            code = ""
        except DecisionCallError as exc:
            code = exc.code
        engine = laya_type(status=DecisionStatus.READY)
        close = _close_allowed(engine, proposal_type)
        ended = "refusal" if code == "prompt_over_cap" and len(calls) == before else "allow"
        return DrillResult("oversized_prompt", ended, close, code or "none")


def _drill_note_too_long(laya_type, proposal_type, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("note_too_long")
        raise AssertionError("a 4001-character note must not be posted")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "x" * 4_001))
        close = _close_allowed(engine, proposal_type)
        stayed = engine.status is DecisionStatus.READY and len(calls) == before
        refused = not verdict.allow and verdict.reason == "The note is too long to admit." and stayed
        ended = "refusal" if refused else "allow"
        return DrillResult("note_too_long", ended, close, verdict.reason)


def _drill_empty_live(laya_type, proposal_type, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("empty")
        raise AssertionError("an empty note must not be posted")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="chat",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya_ollama import allowlist_entry  # noqa: PLC0415

        entry = allowlist_entry(_DRILL_TAG)
        assert entry is not None
        decision = evaluate_free_text(
            mode="live",
            action="BUY",
            rationale="   ",
            requested_quantity=20,
            degraded_ceiling=1,
            client=_Capture(_FailClosedClient()),
        )
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        close = _close_allowed(engine, proposal_type)
        refused = decision.effect == "deny" and _failure_token(decision) == "note_absent" and len(calls) == before
        ended = "refusal" if refused else "allow"
        return DrillResult("empty_note_live", ended, close, "note_absent")


def _drill_runtime_too_old(laya_type, proposal_type, detail_fn, set_transport, calls: list[str]) -> DrillResult:
    before = len(calls)

    def poster(*_args: Any) -> Any:
        calls.append("old")
        raise AssertionError("systemone on v0.32 must not be posted")

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST, version="0.32.0")
    with _drill_transport(
        set_transport,
        route="systemone",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and len(calls) == before else "allow"
        return DrillResult("runtime_too_old", ended, close, _detail(engine, detail_fn))


def _drill_advisory_choices(laya_type, proposal_type, pause: str, set_transport, calls: list[str]) -> DrillResult:
    def poster(*_args: Any) -> Any:
        calls.append("advisory")
        return {"choices": [{"message": {"content": "{}"}}], "answers": _option_payload(0.1)["answers"]}

    snapshot = _ready_snapshot(_EXAMPLE_DIGEST)
    with _drill_transport(
        set_transport,
        route="systemone",
        snapshot=snapshot,
        poster=poster,
        session_digest=_EXAMPLE_DIGEST,
    ):
        from flinttrade_engine.laya import DecisionStatus  # noqa: PLC0415

        engine = laya_type(status=DecisionStatus.READY)
        verdict = engine.admit(_proposal(proposal_type, "Buying because the EXAMPLE level 100 held."))
        close = _close_allowed(engine, proposal_type)
        ended = "down" if not verdict.allow and verdict.reason == pause else "allow"
        return DrillResult("advisory_choices", ended, close, "malformed" if ended == "down" else "allow")


if __name__ == "__main__":
    raise SystemExit(main())
