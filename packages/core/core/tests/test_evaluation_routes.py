"""Mounted core route produces immutable evidence, retaining compatibility."""
import pytest
from flinttrade_backtest.base_strategy import BaseBacktestStrategy
from flinttrade_backtest.data_connector import DataConnector, DataResult
from flinttrade_backtest.strategies import STRATEGY_REGISTRY
from flinttrade_core.evaluation import EvaluationStore

pytestmark = pytest.mark.integration


class Candidate(BaseBacktestStrategy):
    broken = False
    def on_bar(self, bar):
        if self.broken:
            raise RuntimeError("synthetic failed candidate")


def test_mounted_trial_readback_preserves_failures_and_version_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core.app import create_flask_app
    monkeypatch.setitem(STRATEGY_REGISTRY, "EvidenceCandidate", Candidate)
    monkeypatch.setattr(DataConnector, "load", lambda *a, **kw: DataResult(
        bars=[{"timestamp": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}],
        source="synthetic-test"))
    app = create_flask_app()
    app.config["EVALUATION_STORE"] = EvaluationStore(tmp_path / "evidence.db")
    client = app.test_client()
    headers = {"X-API-Key": "synthetic-key"}
    body = {"strategy": "EvidenceCandidate", "symbol": "TEST", "interval": "1d"}
    good = client.post("/api/v1/backtest/run", json=body, headers=headers)
    assert good.status_code == 200
    trial = good.headers["X-Trial-Id"]
    record = client.get(f"/api/v1/backtest/trials/{trial}", headers=headers)
    assert record.status_code == 200
    assert record.json["data"]["status"] == "completed"
    experiment = client.get(f"/api/v1/backtest/experiments/{good.headers['X-Experiment-Id']}", headers=headers)
    assert experiment.json["data"]["manifest"]["strategy"]["name"] == "EvidenceCandidate"
    assert experiment.json["data"]["manifest"]["data"]["source"] == "synthetic-test"
    monkeypatch.setattr(Candidate, "broken", True)
    failed = client.post("/api/v1/backtest/run", json=body, headers=headers)
    assert failed.status_code == 500
    failed_trial = failed.headers["X-Trial-Id"]
    assert failed_trial != trial
    readback = client.get(f"/api/v1/backtest/trials/{failed_trial}", headers=headers).json["data"]
    assert readback["status"] == "failed"
    assert readback["evidence"]["stage"] == "simulation"
    assert client.get(f"/api/v1/backtest/trials/{trial}", headers=headers).json == record.json


@pytest.mark.parametrize("path", ["training/jobs", "adoptions"])
def test_optional_mutators_are_mounted_but_refuse_without_core_owner(monkeypatch, path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    client = app.test_client()
    assert client.post(f"/api/v1/backtest/{path}", json={}).status_code == 401
    response = client.post(f"/api/v1/backtest/{path}", json={}, headers={"X-API-Key": "synthetic-key"})
    assert response.status_code == 503
    assert response.json["status"] == "unavailable"


def test_mounted_training_uses_durable_job_owner_and_exact_cancel(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.training_jobs import TrainingJobs, UnslothTrainingBackend, UNSLOTH_PIN
    calls = []
    def gateway(op, method, path, payload):
        calls.append((op, payload))
        return {"status": "pending", "job_id": "remote-1"}
    jobs = TrainingJobs(tmp_path / "jobs.db", UnslothTrainingBackend(version=UNSLOTH_PIN,
        principal_role="owner", capacity_isolated=True, gateway=gateway))
    app = create_flask_app()
    app.config["TRAINING_JOBS"] = jobs
    client = app.test_client()
    headers = {"X-API-Key": "synthetic-key"}
    payload = {"request_id": "fixture", "payload": {"model_name": "fixture", "training_type": "lora",
               "format_type": "chatml", "local_datasets": ["uploaded-fixture.jsonl"]}, "lineage": {"dataset": "batch-v1"}}
    result = client.post("/api/v1/backtest/training/jobs", json=payload, headers=headers)
    assert result.status_code == 202
    assert result.json["data"] == jobs.get("fixture")
    assert client.get("/api/v1/backtest/training/jobs/fixture", headers=headers).json == result.json
    for raw in ("[]", "null", "{bad"):
        assert client.post("/api/v1/backtest/training/jobs", data=raw, content_type="application/json", headers=headers).status_code == 400
    assert len(calls) == 1
    cancel = client.post("/api/v1/backtest/training/jobs/fixture/cancel", json={}, headers=headers)
    assert cancel.status_code == 202
    assert cancel.json["data"]["cancellation"] == "requested"
    assert calls[-1][1] == {"expected_job_id": "remote-1", "save": False}


def test_mounted_sealed_score_uses_core_prospective_evidence_not_client_assertions(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core.app import create_flask_app
    manifest = {"schema_version": 1, "data": "d", "model": "m", "skill": "s", "strategy": "v1",
                "config": "c", "evaluator": "independent", "producer": "trainer", "role": "admission"}
    store = EvaluationStore(tmp_path / "evidence.db", graders={"independent": lambda candidate, rows: {"correct": 1}})
    store.freeze("suite", {name: [{"id": name, "group": name, "as_of": i, "gold": "sealed"}]
                           for i, name in enumerate(("development", "calibration", "final"))},
                 evaluator="independent", policy={"thresholds": {"correct": {"min": 1}}, "budgets": {"max_trials": 1}})
    trial = store.begin(store.create(manifest))
    app = create_flask_app()
    app.config["EVALUATION_STORE"] = store
    client = app.test_client()
    headers = {"X-API-Key": "synthetic-key"}
    path = "/api/v1/backtest/evaluation/suites/suite/score"
    assert client.post(path, json={"trial_id": trial}, headers=headers).status_code == 503
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda identity: {"candidate": manifest, "receipt": "fixture-shadow"}
    assert client.post(path, json={"trial_id": trial, "qualified": True}, headers=headers).status_code == 400
    response = client.post(path, json={"trial_id": trial}, headers=headers)
    assert response.status_code == 200
    assert response.json["data"]["evidence"]["qualified"] is True
    assert "sealed" not in response.get_data(as_text=True)
    assert client.post(path, json={"trial_id": trial}, headers=headers).status_code == 422
