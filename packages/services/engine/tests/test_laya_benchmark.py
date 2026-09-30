"""Offline harness for the Laya free-text seam.

The fixture is synthetic Example text. It is not the Researcher's draft set.
"""

from __future__ import annotations

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
    assert "wrong_admit_95_upper=3/1" in report.render()
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
