"""Mounted core route produces immutable evidence, retaining compatibility."""
import pytest
from flinttrade_backtest.base_strategy import BaseBacktestStrategy
from flinttrade_backtest.data_connector import DataConnector, DataResult
from flinttrade_backtest.strategies import STRATEGY_REGISTRY
from flinttrade_core.evaluation import EvaluationStore
from flinttrade_core.auth_routes import _create_token
from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_run_learning_remote import action
from packages.core.core.tests.test_service_tasks import NOW

pytestmark = [pytest.mark.usefixtures("owned_flask_apps"), pytest.mark.integration]


class Candidate(BaseBacktestStrategy):
    broken = False
    def on_bar(self, bar):
        if self.broken:
            raise RuntimeError("synthetic failed candidate")


def test_mounted_trial_readback_preserves_failures_and_version_identity(monkeypatch, tmp_path, composed):
    owner, supervisor, app, client, connections, calls, headers, desk = composed
    run_id = supervisor.run.run_id
    configuration = f"/v1/model-runs/{run_id}/configuration"
    action(client, headers, configuration, "access", {"operations": ["evaluation.read"],
        "valid_until": NOW.timestamp() + 3600, "evidence": "explicit-synthetic-evaluation-read"})
    monkeypatch.setitem(STRATEGY_REGISTRY, "EvidenceCandidate", Candidate)
    monkeypatch.setattr(DataConnector, "load", lambda *a, **kw: DataResult(
        bars=[{"timestamp": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1}],
        source="synthetic-test"))
    app.config["EVALUATION_STORE"] = EvaluationStore(tmp_path / "evidence.db")
    body = {"strategy": "EvidenceCandidate", "symbol": "TEST", "interval": "1d", "run_id": run_id}
    good = client.post("/api/v1/backtest/run", json=body, headers=headers)
    assert good.status_code == 200
    trial = good.headers["X-Trial-Id"]
    record = client.get(f"/api/v1/backtest/trials/{trial}", headers=headers)
    assert record.status_code == 200
    assert record.json["data"]["status"] == "completed"
    experiment = client.get(f"/api/v1/backtest/experiments/{good.headers['X-Experiment-Id']}", headers=headers)
    assert experiment.json["data"]["manifest"]["strategy"]["name"] == "EvidenceCandidate"
    assert experiment.json["data"]["manifest"]["data"]["source"] == "synthetic-test"
    assert experiment.json["data"]["manifest"]["control_scope"] == vars(owner.runs.scope(run_id))
    # Keep this legacy synthetic loader honest: scoped read permission does
    # not turn its data into an attested immutable history snapshot.
    assert experiment.json["data"]["manifest"]["data"]["provenance_status"] == "unqualified_legacy"
    monkeypatch.setattr(Candidate, "broken", True)
    failed = client.post("/api/v1/backtest/run", json=body, headers=headers)
    assert failed.status_code == 500
    failed_trial = failed.headers["X-Trial-Id"]
    assert failed_trial != trial
    readback = client.get(f"/api/v1/backtest/trials/{failed_trial}", headers=headers).json["data"]
    assert readback["status"] == "failed"
    assert readback["evidence"]["stage"] == "simulation"
    assert client.get(f"/api/v1/backtest/trials/{trial}", headers=headers).json == record.json
    assert calls == [], "Evidence readback must not dispatch provider work"
    for identity in (trial, failed_trial):
        url = f"/api/v1/backtest/trials/{identity}"
        for rejected_headers in ({}, {"X-API-Key": "synthetic-key"}):
            refused = client.get(url, headers=rejected_headers)
            assert refused.status_code == 403
            assert refused.json == {"status": "error", "code": "operator_session_required"}
            assert refused.headers["Cache-Control"] == "no-store"
    action(client, headers, configuration, "access", {"operations": [],
        "valid_until": NOW.timestamp() + 3600, "evidence": "explicit-synthetic-read-revocation"}, revision=1)
    for identity in (trial, failed_trial):
        assert client.get(f"/api/v1/backtest/trials/{identity}", headers=headers).status_code == 403
    assert app.config["EVALUATION_STORE"].trial(trial)["status"] == "completed"
    assert app.config["EVALUATION_STORE"].trial(failed_trial)["status"] == "failed"


@pytest.mark.parametrize("path", ["training/jobs", "adoptions"])
def test_optional_mutators_are_mounted_but_refuse_without_core_owner(monkeypatch, path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-key")
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    client = app.test_client()
    url = f"/api/v1/backtest/{path}"
    for headers in ({}, {"X-API-Key": "synthetic-key"}):
        refused = client.post(url, json={}, headers=headers)
        assert refused.status_code == 403
        assert refused.json == {"status": "error", "code": "operator_session_required"}
    with app.app_context():
        token = _create_token("synthetic-evaluation", scopes=("admin.services.write",))
    # The factory now always installs the owner. Exercise the same unavailable
    # scenario by explicitly removing that dependency, not by bypassing auth.
    assert app.config["MODEL_RUN_SERVICES"] is not None
    monkeypatch.setitem(app.config, "MODEL_RUN_SERVICES", None)
    body = ({"request_id": "fixture", "payload": {}, "lineage": {"run_id": "fixture"}}
            if path == "training/jobs" else
            {"request_id": "fixture", "run_id": "fixture", "role": "reasoning",
             "candidate": "fixture", "expected_generation": 0})
    response = client.post(url, json=body, headers={"Authorization": "Bearer " + token})
    assert response.status_code == 503, response.json
    assert response.json == {"status": "unavailable", "code": "model_control_unavailable"}


def test_mounted_training_uses_durable_job_owner_and_exact_cancel(composed):
    import json
    from packages.core.core.tests.test_training_integration import prepared

    # composed constructs the normal factory and registers the actual run;
    # prepared grants only its explicit synthetic dataset/recipient/operation.
    owner, supervisor, app, client, store, calls, headers, desk = composed
    training_payload, run_id, grant, batch, ledger = prepared(composed)
    payload = {"request_id": "training-one", "payload": training_payload,
               "lineage": {"dataset": batch, "run_id": run_id}}
    for rejected_headers in ({}, {"X-API-Key": "synthetic-key"}):
        refused = client.post("/api/v1/backtest/training/jobs", json=payload, headers=rejected_headers)
        assert refused.status_code == 403
        assert refused.json == {"status": "error", "code": "operator_session_required"}
    assert calls == []
    result = client.post("/api/v1/backtest/training/jobs", json=payload, headers=headers)
    assert result.status_code == 202, result.json
    assert result.json["data"] == owner.training_owner().get("training-one")
    assert client.get("/api/v1/backtest/training/jobs/training-one", headers=headers).json == result.json
    for raw in ("[]", "null", "{bad"):
        assert client.post("/api/v1/backtest/training/jobs", data=raw, content_type="application/json", headers=headers).status_code == 400
    assert len(calls) == 1
    cancel = client.post("/api/v1/backtest/training/jobs/training-one/cancel", json={}, headers=headers)
    assert cancel.status_code == 202
    assert cancel.json["data"]["cancellation"] == "requested"
    assert json.loads(calls[-1].content) == {"expected_job_id": "remote-one", "save": False}


def test_mounted_sealed_score_uses_core_prospective_evidence_not_client_assertions(composed, tmp_path):
    owner, supervisor, app, client, connections, calls, headers, desk = composed
    manifest = {"schema_version": 1, "data": "d", "model": "m", "skill": "s", "strategy": "v1",
                "config": "c", "evaluator": "independent", "producer": "trainer", "role": "admission",
                "control_scope": vars(owner.runs.scope(supervisor.run.run_id))}
    store = EvaluationStore(tmp_path / "evidence.db", graders={"independent": lambda candidate, rows: {"correct": 1}})
    store.freeze("suite", {name: [{"id": name, "group": name, "as_of": i, "gold": "sealed"}]
                           for i, name in enumerate(("development", "calibration", "final"))},
                 evaluator="independent", policy={"thresholds": {"correct": {"min": 1}}, "budgets": {"max_trials": 1}})
    trial = store.begin(store.create(manifest))
    app.config["EVALUATION_STORE"] = store
    configuration = f"/v1/model-runs/{supervisor.run.run_id}/configuration"
    action(client, headers, configuration, "access", {"operations": ["evaluation.score"],
        "valid_until": NOW.timestamp() + 3600, "evidence": "explicit-synthetic-evaluation-policy"})
    action(client, headers, configuration, "evaluation", {"trial": trial, "suite": "suite"})
    path = "/api/v1/backtest/evaluation/suites/suite/score"
    assert store.suite("suite")["consumed_by"] is None
    for rejected_headers in ({}, {"X-API-Key": "synthetic-key"}):
        refused = client.post(path, json={"trial_id": trial}, headers=rejected_headers)
        assert refused.status_code == 403
        assert refused.json == {"status": "error", "code": "operator_session_required"}
    assert store.suite("suite")["consumed_by"] is None
    assert client.post(path, json={"trial_id": trial}, headers=headers).status_code == 503
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda identity: {"candidate": manifest, "receipt": "fixture-shadow"}
    assert client.post(path, json={"trial_id": trial, "qualified": True}, headers=headers).status_code == 400
    response = client.post(path, json={"trial_id": trial}, headers=headers)
    assert response.status_code == 200
    assert response.json["data"]["evidence"]["qualified"] is True
    assert "sealed" not in response.get_data(as_text=True)
    assert client.post(path, json={"trial_id": trial}, headers=headers).status_code == 422
