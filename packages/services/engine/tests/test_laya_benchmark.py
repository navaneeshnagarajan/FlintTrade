"""Offline harness for the Laya free-text seam.

The fixture is synthetic Example text. It is not the Researcher's draft set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flinttrade_engine.laya_benchmark import (
    BenchmarkCase,
    BenchmarkCaseError,
    file_sha256,
    load_cases,
    load_exclude_ids,
    main,
    run_benchmark,
    select_split,
    state_for_case,
)
from flinttrade_engine.laya_decision import state_for_note

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "laya_benchmark_example.jsonl"
_POLICY = Path(__file__).resolve().parents[1] / "src" / "flinttrade_engine" / "laya_policy.toml"
_HIDDEN = "EXAMPLE-HIDDEN-SYMBOL"


def _payload(deny_p: float) -> dict[str, object]:
    other = 1.0 - deny_p
    return {
        "answers": {
            "rationale": {"probabilities": {"A": other, "B": deny_p}},
            "tilt": {"probabilities": {"A": deny_p, "B": other}},
            "side": {"probabilities": {"A": deny_p, "B": other}},
        }
    }


class _Client:
    def __init__(self, deny_p: float = 0.1) -> None:
        self.deny_p = deny_p
        self.states: list[str] = []
        self.last_proof = "runtime"

    def decide(self, state: str, questions: object) -> dict[str, object]:
        del questions
        self.states.append(state)
        return _payload(self.deny_p)


class _Flip:
    """Allow on the first call and hard-deny on the second."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_proof = "runtime"

    def decide(self, state: str, questions: object) -> dict[str, object]:
        del state, questions
        self.calls += 1
        return _payload(0.1 if self.calls % 2 else 0.95)


class _TiltOnly:
    last_proof = "runtime"

    def decide(self, state: str, questions: object) -> dict[str, object]:
        del state, questions
        return {
            "answers": {
                "rationale": {"probabilities": {"A": 0.9, "B": 0.1}},
                "tilt": {"probabilities": {"A": 0.95, "B": 0.05}},
                "side": {"probabilities": {"A": 0.1, "B": 0.9}},
            }
        }


def _case(**overrides: object) -> BenchmarkCase:
    raw = {
        "id": "ex-one",
        "pair_id": "ex-one",
        "split": "dev",
        "question": "rationale",
        "note": "Buying because the EXAMPLE level 100 held.",
        "side": "BUY",
        "mode": "practice",
        "quantity": 20,
        "label": "admit",
        "group": "core",
        "difficulty": "easy",
        "path": "host",
        "why": "example",
    }
    raw.update(overrides)
    return BenchmarkCase(**raw)  # type: ignore[arg-type]


def _reaches(case: BenchmarkCase) -> bool:
    note = case.note.strip()
    return bool(note) and len(note) <= 4000


@pytest.mark.unit
def test_fixture_keeps_only_side_on_the_model_state() -> None:
    cases = load_cases(_FIXTURE)
    client = _Client()
    report = run_benchmark(cases, client, file_sha256_hex=file_sha256(_FIXTURE), split="all")
    reached = [case for case in cases if _reaches(case)]
    assert len(client.states) == len(reached)
    for case, state in zip(reached, client.states, strict=True):
        assert state == state_for_case(case)
        assert state == state_for_note(action=case.side, rationale=case.note)
        assert _HIDDEN not in state
        assert "quantity" not in state.lower()
        assert "20" not in state
    buy = next(case for case in cases if case.id == "ex-side-01-a")
    sell = next(case for case in cases if case.id == "ex-side-01-b")
    assert buy.note == sell.note
    assert state_for_case(buy).replace("BUY", "SELL") == state_for_case(sell)
    by_id = {row.case.id: row for row in report.outcomes}
    assert by_id["ex-len-01-b"].failure == "note_too_long"
    assert by_id["ex-len-01-b"].probs == "none"
    assert by_id["ex-len-01-b"].band == "correct"
    assert by_id["ex-empty-01-a"].failure == "note_absent"
    assert by_id["ex-empty-01-a"].band == "correct"
    assert by_id["ex-empty-01-b"].band == "correct"
    assert by_id["ex-len-01-a"].failure == "none"
    assert by_id["ex-len-02-a"].failure == "none"
    assert len(next(case.note for case in cases if case.id == "ex-len-02-a").strip()) == 4000
    assert by_id["ex-rat-01-b"].band == "wrong_admit"
    assert by_id["ex-rat-01-a"].band == "correct"
    assert "B=0.1" in by_id["ex-rat-01-a"].probs
    overall = next(line for line in report.render().splitlines() if line.startswith("question overall "))
    assert "abstains=0" in overall
    assert "wrong_denies=0" in overall


@pytest.mark.unit
def test_abstain_is_not_a_wrong_admit_or_a_wrong_deny() -> None:
    admit = _case(label="admit", mode="live")
    deny = _case(id="ex-deny", label="deny", mode="practice")
    report = run_benchmark((admit, deny), _Client(0.6))
    assert [row.band for row in report.outcomes] == ["abstain", "abstain"]
    text = report.render()
    assert "abstains=2" in text
    assert "wrong_admits=0" in text
    assert "wrong_denies=0" in text
    assert "B=0.6" in report.outcomes[0].probs
    assert "0.6000" not in report.outcomes[0].probs


@pytest.mark.unit
def test_hard_deny_on_another_question_is_other() -> None:
    probed = _case(question="rationale", label="deny")
    admitted = _case(id="ex-admit", label="admit")
    report = run_benchmark((probed, admitted), _TiltOnly())
    assert report.outcomes[0].band == "other"
    assert report.outcomes[1].band == "wrong_deny"
    text = report.render()
    assert "wrong_admits=0" in text
    assert "other=1" in text
    assert "wrong_denies=1" in text


@pytest.mark.unit
def test_full_allow_of_a_clamp_label_is_a_wrong_admit() -> None:
    report = run_benchmark((_case(label="clamp"),), _Client(0.1))
    assert report.outcomes[0].band == "wrong_admit"


@pytest.mark.unit
def test_down_is_not_a_wrong_admit() -> None:
    class _Down:
        last_proof = ""

        def decide(self, state: str, questions: object) -> dict[str, object]:
            del state, questions
            from flinttrade_engine.laya_decision import DecisionCallError

            raise DecisionCallError("runtime_down")

    report = run_benchmark((_case(label="deny"), _case(id="ex-ok", label="admit")), _Down())
    assert [row.band for row in report.outcomes] == ["down", "down"]
    assert "wrong_admits=0" in report.render()
    assert "wrong_admit_95_upper=undefined" in report.render()
    assert "cannot_claim_under_1_percent=yes" in report.render()


@pytest.mark.unit
def test_stability_uses_the_band_and_counts_use_the_first_repeat() -> None:
    report = run_benchmark((_case(label="admit"),), _Flip(), repeats=2)
    assert report.outcomes[0].band == "correct"
    assert report.outcomes[0].signatures[0] != report.outcomes[0].signatures[1]
    assert "stability stable=0 unstable=1" in report.render()


@pytest.mark.unit
def test_report_covers_group_difficulty_split_and_hash() -> None:
    cases = load_cases(_FIXTURE)
    digest = file_sha256(_FIXTURE)
    report = run_benchmark(select_split(cases, "dev"), _Client(), split="dev", file_sha256_hex=digest)
    text = report.render()
    assert f"split=dev file_sha256={digest}" in text
    assert "group core " in text
    assert "group hinglish " in text
    assert "group injection " in text
    assert "group empty_note " in text
    assert "group length " in text
    assert "group unset " in text
    assert "difficulty easy " in text
    assert "difficulty hard " in text
    assert "difficulty unset " in text
    assert "latency_bar_ms=3000.0" in text
    assert "latency_p95_within_bar=yes" in text
    overall = next(line for line in text.splitlines() if line.startswith("question overall "))
    parts = dict(token.split("=", 1) for token in overall.split() if "=" in token)
    total = sum(int(parts[name]) for name in ("wrong_admits", "wrong_denies", "abstains", "downs", "correct", "other"))
    assert total == int(parts["n"])
    assert "n_deny=" in text
    assert "cannot_claim_under_1_percent=yes" in text


@pytest.mark.unit
def test_exclude_file_prints_the_report_with_and_without_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exclude = tmp_path / "exclude.txt"
    exclude.write_text("# borderline\n\nex-rat-01-b\n", encoding="utf-8")
    assert load_exclude_ids(exclude) == frozenset({"ex-rat-01-b"})
    code = main(
        [
            "--cases",
            str(_FIXTURE),
            "--split",
            "dev",
            "--stub",
            "--skip-drills",
            "--exclude",
            str(exclude),
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert text.count(f"file_sha256={file_sha256(_FIXTURE)}") == 2
    assert "excluded=no" in text
    assert "excluded=ex-rat-01-b" in text
    assert "model_score=no" in text
    assert "Stub results are not a model score." in text
    blocks = text.split("candidate ")
    full = blocks[1]
    held = blocks[2]
    assert "id=ex-rat-01-b" in full
    assert "id=ex-rat-01-b" not in held


@pytest.mark.unit
def test_tune_is_refused_on_test_and_does_not_edit_dev_thresholds(capsys: pytest.CaptureFixture[str]) -> None:
    before = _POLICY.read_bytes()
    assert main(["--cases", str(_FIXTURE), "--split", "test", "--tune", "--skip-drills"]) == 2
    assert capsys.readouterr().out.strip() == "error=refusing to tune on test"
    assert main(["--cases", str(_FIXTURE), "--tune", "--skip-drills"]) == 2
    assert "refusing to tune on test" in capsys.readouterr().out
    assert main(["--cases", str(_FIXTURE), "--split", "dev", "--tune", "--skip-drills"]) == 0
    tuned = capsys.readouterr().out
    assert "tune=not_applied thresholds_unchanged=yes" in tuned
    assert "test_scored_once=yes" not in tuned
    assert _POLICY.read_bytes() == before
    assert main(["--cases", str(_FIXTURE), "--split", "test", "--skip-drills"]) == 0
    scored = capsys.readouterr().out
    assert "test_scored_once=yes" in scored
    assert "split=test " in scored
    assert "id=ex-side-01-a" in scored
    assert "id=ex-rat-01-a" not in scored


@pytest.mark.unit
def test_order_field_is_not_accepted(tmp_path: Path) -> None:
    raw = (
        '{"id":"x","pair_id":"x","split":"dev","question":"rationale","note":"n",'
        '"order":{"action":"BUY"},"label":"admit"}\n'
    )
    path = tmp_path / "bad.jsonl"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(BenchmarkCaseError, match="order_context"):
        load_cases(path)


@pytest.mark.unit
def test_unknown_fields_are_ignored(tmp_path: Path) -> None:
    line = (
        '{"id":"ex-extra","pair_id":"ex-extra","split":"dev","question":"side","note":"Going long.",'
        '"order_context":{"side":"SELL","symbol":"EXAMPLE-HIDDEN-SYMBOL","quantity":20,"mode":"practice"},'
        '"label":"deny","future_field":1}\n'
    )
    path = tmp_path / "one.jsonl"
    path.write_text(line, encoding="utf-8")
    case = load_cases(path)[0]
    assert case.side == "SELL"
    assert case.group == "unset"
    assert case.quantity == 20
    assert _HIDDEN not in state_for_case(case)


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["lvie", "paper", "explore", 1, False, 0, [], {}])
def test_unsupported_case_modes_are_rejected(tmp_path: Path, mode: object) -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8").splitlines()[0])
    raw["order_context"]["mode"] = mode
    path = tmp_path / "bad-mode.jsonl"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(BenchmarkCaseError, match="line 1 order_context.mode must be practice or live"):
        load_cases(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "mode,expected",
    [(None, "practice"), ("", "practice"), ("  ", "practice"), ("Practice", "practice"), (" LIVE ", "live")],
)
def test_supported_case_modes_and_empty_default(tmp_path: Path, mode: object, expected: str) -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8").splitlines()[0])
    raw["order_context"]["mode"] = mode
    path = tmp_path / "mode.jsonl"
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert load_cases(path)[0].mode == expected
    del raw["order_context"]["mode"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert load_cases(path)[0].mode == "practice"


@pytest.mark.unit
@pytest.mark.parametrize("unreadable", ["missing", "directory"])
def test_hash_read_errors_are_benchmark_errors(tmp_path: Path, unreadable: str) -> None:
    path = tmp_path / "cases.jsonl"
    if unreadable == "directory":
        path.mkdir()

    with pytest.raises(BenchmarkCaseError, match="could not read cases.jsonl"):
        file_sha256(path)


@pytest.mark.unit
@pytest.mark.parametrize("unreadable", ["missing", "directory"])
def test_cli_unreadable_case_file_returns_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], unreadable: str
) -> None:
    path = tmp_path / "cases.jsonl"
    if unreadable == "directory":
        path.mkdir()

    assert main(["--cases", str(path), "--stub", "--skip-drills"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "error=could not read cases.jsonl\n"
    assert not captured.err


class _Unavailable:
    last_proof = ""

    def decide(self, state: str, questions: object) -> dict[str, object]:
        del state, questions
        from flinttrade_engine.laya_decision import DecisionCallError

        raise DecisionCallError("runtime_down")


def _deny_cases(count: int, **overrides: object) -> tuple[BenchmarkCase, ...]:
    return tuple(
        _case(**{"id": f"ex-deny-{i}", "pair_id": f"ex-pair-{i}", "label": "deny", **overrides}) for i in range(count)
    )


def _metric(text: str, name: str) -> str:
    return next(token.split("=", 1)[1] for token in text.split() if token.startswith(f"{name}="))


@pytest.mark.unit
def test_all_down_is_unavailable_not_a_model_score_or_latency_sample() -> None:
    text = run_benchmark(_deny_cases(301), _Unavailable()).render()
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "model_score") == "no"
    assert _metric(text, "n_model_scored_repeats") == "0"
    assert _metric(text, "n_model_unavailable_repeats") == "301"
    assert _metric(text, "n_qualifying_deny_pairs") == "0"
    assert _metric(text, "wrong_admit_95_upper") == "undefined"
    assert _metric(text, "latency_p50_ms") == "unavailable"
    assert _metric(text, "latency_p95_within_bar") == "no"


@pytest.mark.unit
def test_down_heavy_run_cannot_hide_the_successful_model_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    class _OneModelResult(_Client):
        def decide(self, state: str, questions: object) -> dict[str, object]:
            if not self.states:
                return super().decide(state, questions)
            return _Unavailable().decide(state, questions)

    ticks = iter([0.0, 4.0, *[value for i in range(1, 301) for value in (10.0 * i, 10.0 * i + 0.001)]])
    monkeypatch.setattr("flinttrade_engine.laya_benchmark.time.perf_counter", lambda: next(ticks))
    text = run_benchmark(_deny_cases(301), _OneModelResult(0.95)).render()
    assert _metric(text, "latency_p95_within_bar") == "no"
    assert _metric(text, "latency_p95_ms") == "4000.000"
    assert _metric(text, "n_model_scored_repeats") == "1"
    assert _metric(text, "n_model_unavailable_repeats") == "300"
    assert _metric(text, "n_qualifying_deny_pairs") == "1"
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "wrong_admit_95_upper") == "undefined"


@pytest.mark.unit
@pytest.mark.parametrize("note", ["", " " * 2, "x" * 4001], ids=["empty", "whitespace", "too_long"])
def test_deterministic_bypasses_never_supply_model_evidence(note: str) -> None:
    client = _Client(0.95)
    text = run_benchmark(_deny_cases(301, note=note, mode="live"), client).render()
    assert not client.states
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "model_score") == "no"
    assert _metric(text, "n_model_eligible_repeats") == "0"
    assert _metric(text, "n_qualifying_deny_pairs") == "0"
    assert _metric(text, "latency_p95_within_bar") == "no"


@pytest.mark.unit
@pytest.mark.parametrize("boundary", ["load", "run"])
def test_duplicate_case_ids_are_rejected_before_any_scoring(tmp_path: Path, boundary: str) -> None:
    client = _Client(0.95)
    with pytest.raises(BenchmarkCaseError, match="duplicate case id"):
        if boundary == "run":
            run_benchmark((_case(), _case(pair_id="another-pair")), client)
        else:
            first = _FIXTURE.read_text(encoding="utf-8").splitlines()[0]
            path = tmp_path / "duplicate.jsonl"
            path.write_text(f"{first}\n{first}\n", encoding="utf-8")
            load_cases(path)
    assert not client.states


@pytest.mark.unit
def test_pair_members_count_once_for_qualifying_deny_evidence() -> None:
    text = run_benchmark(_deny_cases(301, pair_id="one-pair"), _Client(0.95), repeats=2).render()
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "n_qualifying_deny_cases") == "301"
    assert _metric(text, "n_qualifying_deny_pairs") == "1"
    assert _metric(text, "wrong_admit_95_upper") == "3/1"
    assert "Pair IDs are bookkeeping, not proof of statistical independence." in text


@pytest.mark.unit
def test_later_repeat_wrong_admit_blocks_claim_but_preserves_first_repeat_tallies() -> None:
    class _LaterAllow(_Client):
        def decide(self, state: str, questions: object) -> dict[str, object]:
            self.deny_p = 0.95 if len(self.states) % 2 == 0 else 0.1
            return super().decide(state, questions)

    report = run_benchmark(_deny_cases(301), _LaterAllow(), repeats=2)
    assert all(row.band == "correct" for row in report.outcomes)
    text = report.render()
    assert "question overall n=301 n_admit=0 n_deny=301 n_clamp=0 wrong_admits=0" in text
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "repeat_wrong_admits") == "301"
    assert _metric(text, "wrong_admit_95_upper") == "undefined"


@pytest.mark.unit
def test_later_unavailable_repeat_blocks_otherwise_sufficient_unique_pairs() -> None:
    class _LastDown(_Client):
        def decide(self, state: str, questions: object) -> dict[str, object]:
            if len(self.states) == 603:
                return _Unavailable().decide(state, questions)
            return super().decide(state, questions)

    text = run_benchmark(_deny_cases(302), _LastDown(0.95), repeats=2).render()
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "n_qualifying_deny_pairs") == "301"
    assert _metric(text, "n_model_unavailable_repeats") == "1"
    assert _metric(text, "wrong_admit_95_upper") == "undefined"


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["proof_absent", "identity_absent", "malformed", "prompt_over_cap"])
def test_unverified_or_invalid_repeats_cannot_qualify(failure: str) -> None:
    class _Invalid(_Client):
        last_proof = ""

        def decide(self, state: str, questions: object) -> dict[str, object]:
            from flinttrade_engine.laya_decision import DecisionCallError

            if failure == "proof_absent":
                self.last_proof = ""
                return super().decide(state, questions)
            if failure == "malformed":
                return {"answers": {}}
            raise DecisionCallError(failure)

    text = run_benchmark(_deny_cases(301), _Invalid(0.95)).render()
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "model_score") == "no"
    assert _metric(text, "n_model_unavailable_repeats") == "301"
    assert _metric(text, "n_qualifying_deny_pairs") == "0"
    assert _metric(text, "latency_p95_within_bar") == "no"


@pytest.mark.unit
def test_stub_never_qualifies_even_if_all_deny_answers_are_correct() -> None:
    text = run_benchmark(_deny_cases(301), _Client(0.95), stub=True).render()
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "model_score") == "no"
    assert _metric(text, "n_model_scored_repeats") == "0"
    assert _metric(text, "n_qualifying_deny_pairs") == "0"
    assert _metric(text, "latency_p95_within_bar") == "no"
    assert _metric(text, "wrong_admit_95_upper") == "undefined"


@pytest.mark.unit
@pytest.mark.parametrize("count,claim", [(300, "yes"), (301, "no")])
def test_eligible_control_counts_unique_pairs_not_repeated_model_calls(count: int, claim: str) -> None:
    text = run_benchmark(_deny_cases(count), _Client(0.95), repeats=2).render()
    assert _metric(text, "n_qualifying_deny_pairs") == str(count)
    assert _metric(text, "n_model_scored_repeats") == str(count * 2)
    assert _metric(text, "n_model_unavailable_repeats") == "0"
    assert _metric(text, "model_score") == "yes"
    assert _metric(text, "wrong_admit_95_upper") == f"3/{count}"
    assert _metric(text, "cannot_claim_under_1_percent") == claim
    assert "Pair IDs are bookkeeping, not proof of statistical independence." in text


@pytest.mark.unit
@pytest.mark.parametrize("model", ["", "example:unknown"])
def test_cli_without_an_available_model_explicitly_reports_no_model_score(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], model: str
) -> None:
    import json

    raw = {
        "pair_id": "pair",
        "split": "dev",
        "question": "rationale",
        "note": "Example note",
        "order_context": {"side": "BUY"},
        "label": "deny",
    }
    path = tmp_path / "deny.jsonl"
    path.write_text(
        "".join(json.dumps({**raw, "id": f"case-{i}", "pair_id": f"pair-{i}"}) + "\n" for i in range(301)),
        encoding="utf-8",
    )
    assert main(["--cases", str(path), "--model", model, "--skip-drills"]) == 0
    text = capsys.readouterr().out
    assert _metric(text, "cannot_claim_under_1_percent") == "yes"
    assert _metric(text, "model_score") == "no"
    assert "No verified model inference is available" in text


@pytest.mark.unit
def test_known_stub_cannot_be_misreported_when_caller_omits_stub_flag() -> None:
    from flinttrade_engine.laya_benchmark import _StubAllowClient

    text = run_benchmark((_case(),), _StubAllowClient()).render()
    assert _metric(text, "model_score") == "no"
    assert _metric(text, "stub") == "yes"
    assert _metric(text, "n_model_scored_repeats") == "0"


@pytest.mark.unit
@pytest.mark.parametrize("route", ["chat", "systemone"])
@pytest.mark.parametrize("owned_ready", [True, False])
def test_cli_client_requires_owned_readiness_and_uses_its_version(
    monkeypatch: pytest.MonkeyPatch, route: str, owned_ready: bool
) -> None:
    import json
    from contextlib import contextmanager
    from types import SimpleNamespace

    import flinttrade_engine.laya_ollama as ollama_mod
    from flinttrade_engine.laya_benchmark import _cli_client

    digest = "ab" * 32
    tag = "example:bench"
    locked = f"flinttrade/sha256-{digest}:locked"
    monkeypatch.setattr(ollama_mod, "LAYA_OLLAMA_ALLOWLIST", (ollama_mod.LayaOllamaModel(tag, digest, route),))
    posted: list[tuple[str, str]] = []

    @contextmanager
    def session(model: str):
        assert model == tag
        yield SimpleNamespace(digest=digest, model=locked, base_url="http://127.0.0.1:11435")

    def poster(base: str, path: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        assert base == "http://127.0.0.1:11435"
        assert 0 < timeout <= 3.0
        posted.append((path, str(payload["model"])))
        answers = _payload(0.95)
        return {"message": {"content": json.dumps(answers)}} if route == "chat" else answers

    snapshot = (
        {
            "ready": True,
            "state": "ready",
            "model_present": True,
            "reported_digest": digest,
            "pinned_server_version": "0.35.0",
            "port": 11435,
        }
        if owned_ready
        else None
    )
    ollama_mod.set_laya_ollama_transport_for_tests(session=session, poster=poster, snapshot=lambda _tag: snapshot)
    try:
        report = run_benchmark((_case(label="deny"),), _cli_client(tag))
    finally:
        ollama_mod.reset_laya_ollama_transport_for_tests()
    text = report.render()
    if owned_ready:
        assert report.outcomes[0].band == "correct"
        assert _metric(text, "model_score") == "yes"
        assert posted == [("/api/chat" if route == "chat" else "/v1/systemone", locked)]
    else:
        assert _metric(text, "model_score") == "no"
        assert report.outcomes[0].band == "down"
        assert not posted


@pytest.mark.unit
@pytest.mark.parametrize("route", ["chat", "systemone"])
@pytest.mark.parametrize("requested", ["omitted", "matching", "mismatched"])
def test_cli_report_route_matches_the_reviewed_client_route(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], route: str, requested: str
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    import flinttrade_engine.laya_ollama as ollama_mod

    digest = "ab" * 32
    tag = "example:bench"
    monkeypatch.setattr(ollama_mod, "LAYA_OLLAMA_ALLOWLIST", (ollama_mod.LayaOllamaModel(tag, digest, route),))
    posted: list[str] = []

    @contextmanager
    def session(model: str):
        assert model == tag
        yield SimpleNamespace(
            digest=digest, model=f"flinttrade/sha256-{digest}:locked", base_url="http://127.0.0.1:11435"
        )

    def poster(base: str, path: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        del base, payload, timeout
        posted.append(path)
        answers = _payload(0.95)
        return {"message": {"content": json.dumps(answers)}} if route == "chat" else answers

    snapshot = {
        "ready": True,
        "state": "ready",
        "model_present": True,
        "reported_digest": digest,
        "pinned_server_version": "0.35.0",
        "port": 11435,
    }
    args = ["--cases", str(_FIXTURE), "--model", tag, "--skip-drills"]
    if requested != "omitted":
        selected = route if requested == "matching" else "systemone" if route == "chat" else "chat"
        args.extend(["--route", selected])
    ollama_mod.set_laya_ollama_transport_for_tests(session=session, poster=poster, snapshot=lambda _tag: snapshot)
    try:
        code = main(args)
    finally:
        ollama_mod.reset_laya_ollama_transport_for_tests()

    text = capsys.readouterr().out
    if requested == "mismatched":
        assert code == 2
        assert f"error=requested route does not match reviewed route {route}" in text
        assert not posted
    else:
        assert code == 0
        assert f"candidate tag={tag} route={route} " in text
        assert posted
        assert set(posted) == {"/api/chat" if route == "chat" else "/v1/systemone"}


@pytest.mark.unit
@pytest.mark.parametrize("route", ["chat", "systemone"])
def test_cli_client_exposes_its_reviewed_route_read_only(route: str) -> None:
    from flinttrade_engine.laya_ollama import LayaOllamaModel, OllamaDecisionClient

    client = OllamaDecisionClient(LayaOllamaModel("example:bench", "ab" * 32, route))
    assert client.route == route
    with pytest.raises(AttributeError):
        client.route = "chat" if route == "systemone" else "systemone"


@pytest.mark.unit
@pytest.mark.parametrize("stub", [False, True])
def test_cli_without_a_model_client_does_not_claim_a_route(capsys: pytest.CaptureFixture[str], stub: bool) -> None:
    args = ["--cases", str(_FIXTURE), "--model", "example:unknown", "--route", "systemone", "--skip-drills"]
    if stub:
        args.append("--stub")

    assert main(args) == 0
    text = capsys.readouterr().out
    assert "candidate tag=example:unknown route=unset " in text
    assert _metric(text, "model_score") == "no"
