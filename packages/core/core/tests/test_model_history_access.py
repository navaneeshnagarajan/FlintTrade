"""Read-only history evidence remains scoped separately from run adoption."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted

pytestmark = pytest.mark.integration


def test_history_evidence_read_requires_current_scope_and_never_grants_score(composed):
    from flinttrade_core.evaluation import EvaluationStore
    owner, _supervisor, app, client, store, _calls, headers, desk = composed
    evidence = EvaluationStore(store.workspace_dir / "history-evaluation.sqlite")
    app.config["EVALUATION_STORE"] = evidence
    scope = {"principal_id": desk.owner, "environment": "research", "account_id": None,
             "run_id": "history-only", "generation": 1}
    app.config["DATA_SCOPE_RESOLVER"] = lambda: dict(scope)
    manifest = {"schema_version": 1, "data": {"scope": dict(scope), "snapshot_id": "synthetic"},
                "model": "none", "skill": "none", "strategy": "synthetic", "config": "synthetic",
                "evaluator": "synthetic", "producer": "synthetic", "role": "backtest"}
    experiment = evidence.create(manifest)
    trial = evidence.begin(experiment)
    for path in ("trials/" + trial, "experiments/" + experiment):
        response = client.get("/api/v1/backtest/" + path, headers=headers)
        assert response.status_code == 200, response.json
        assert client.get("/api/v1/backtest/" + path, headers={"X-API-Key": "synthetic-key"}).status_code == 403
    with app.test_request_context("/api/v1/backtest/evaluation/suites/sealed/score", method="POST", headers=headers):
        with pytest.raises(ValueError, match="scope"):
            owner.authorise_evaluation(desk.owner, "score", trial, suite="sealed")
    scope["generation"] = 2
    assert client.get("/api/v1/backtest/trials/" + trial, headers=headers).status_code == 403
    app.config["DATA_SCOPE_RESOLVER"] = lambda: None
    assert client.get("/api/v1/backtest/trials/" + trial, headers=headers).status_code == 403
    manifest["data"] = "unscoped-legacy"
    unscoped = evidence.begin(evidence.create(manifest))
    assert client.get("/api/v1/backtest/trials/" + unscoped, headers=headers).status_code == 403
