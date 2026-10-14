"""Core-owned experiment evidence through public interfaces."""
import pytest

pytestmark = pytest.mark.unit


def manifest():
    return {"schema_version": 1, "data": "data-v1", "model": "none", "skill": "none",
            "strategy": "strategy-v1", "config": "config-v1", "evaluator": "eval-v1",
            "producer": "trainer", "role": "trading", "training_job": None}


def test_trials_are_immutable_with_failure_retention_and_restart(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    store = EvaluationStore(tmp_path / "experiments.db")
    experiment = store.create(manifest())
    trial = store.begin(experiment)
    store.finish(trial, status="failed", evidence={"stage": "simulation", "reason": "bar failure"})
    with pytest.raises(ValueError, match="terminal"):
        store.finish(trial, status="completed", evidence={"score": 9})
    recovered = EvaluationStore(tmp_path / "experiments.db")
    assert recovered.trial(trial)["status"] == "failed"
    assert recovered.experiment(experiment)["manifest"] == manifest()
    assert recovered.begin(experiment) != trial


def test_inflight_trial_is_unknown_not_replayed(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    first = EvaluationStore(tmp_path / "experiments.db")
    trial = first.begin(first.create(manifest()))
    assert EvaluationStore(tmp_path / "experiments.db").trial(trial)["status"] == "unknown"


def test_final_requires_frozen_policy_and_independent_grader_then_is_consumed_once(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    calls = []
    def grader(candidate, rows):
        calls.append((candidate, rows))
        return {"correct": 1.0}
    store = EvaluationStore(tmp_path / "experiments.db", graders={"eval-v1": grader})
    partitions = {"development": [{"id": "d", "group": "d", "as_of": 1}],
                  "calibration": [{"id": "c", "group": "c", "as_of": 2}],
                  "final": [{"id": "f", "group": "f", "as_of": 3, "gold": "secret"}]}
    with pytest.raises(ValueError, match="policy"):
        store.freeze("suite", partitions, evaluator="eval-v1", policy=None)
    policy = {"thresholds": {"correct": {"min": 1}}, "budgets": {"max_trials": 2}}
    store.freeze("suite", partitions, evaluator="eval-v1", policy=policy)
    trial = store.begin(store.create(manifest()))
    with pytest.raises(ValueError, match="prospective"):
        store.score_final("suite", trial, prospective=None)
    receipt = store.score_final("suite", trial, prospective={"candidate": manifest(), "receipt": "shadow-v1"})
    assert receipt["status"] == "completed"
    assert receipt["evidence"]["qualified"] is True
    assert len(calls) == 1
    assert "gold" not in str(store.suite("suite"))
    with pytest.raises(ValueError, match="consumed"):
        store.score_final("suite", store.begin(store.create(manifest())),
                          prospective={"candidate": manifest(), "receipt": "shadow-v1"})
    assert len(calls) == 1


def test_grader_cannot_change_candidate_identity_to_publish_own_result(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    def grader(candidate, rows):
        candidate["strategy"] = "substituted"
        return {"correct": 1}
    store = EvaluationStore(tmp_path / "evidence.db", graders={"eval-v1": grader})
    store.freeze("suite", {k: [{"id": k, "group": k, "as_of": i}]
                          for i, k in enumerate(("development", "calibration", "final"))},
                 evaluator="eval-v1", policy={"thresholds": {"correct": {"min": 1}}, "budgets": {"max_trials": 1}})
    trial = store.begin(store.create(manifest()))
    result = store.score_final("suite", trial, prospective={"candidate": manifest(), "receipt": "shadow"})
    assert result["status"] == "failed"
    assert not result["evidence"]["qualified"]


def test_sealed_labels_cannot_escape_through_extra_grader_output(tmp_path):
    from flinttrade_core.evaluation import EvaluationStore
    store = EvaluationStore(tmp_path / "evidence.db", graders={"eval-v1":
        lambda candidate, rows: {"correct": 1, "debug_rows": rows}})
    store.freeze("suite", {name: [{"id": name, "group": name, "as_of": i, "gold": "PRIVATE_FINAL_LABEL"}]
                          for i, name in enumerate(("development", "calibration", "final"))},
                 evaluator="eval-v1", policy={"thresholds": {"correct": {"min": 1}}, "budgets": {"max_trials": 1}})
    trial = store.begin(store.create(manifest()))
    result = store.score_final("suite", trial, prospective={"candidate": manifest(), "receipt": "shadow"})
    assert "PRIVATE_FINAL_LABEL" not in str(result)
    assert result["evidence"]["metrics"] == {"correct": 1}
