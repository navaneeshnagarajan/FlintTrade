"""Real normal-factory shared data/model owners, not test-only installers."""
from __future__ import annotations

import os
import secrets
import time

import pytest

from flinttrade_core import auth_routes
from packages.core.core.tests.test_data_runtime import manual_record, server_scope
from packages.core.historical.tests.test_history_manifest import history_input

pytestmark = pytest.mark.integration


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    from flinttrade_core.app import create_flask_app

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", secrets.token_urlsafe(32))
    app = create_flask_app()
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    if app.config.get("LIMITER"):
        app.config["LIMITER"].enabled = False
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.invalid", secrets.token_urlsafe(32))
    with app.app_context():
        token = auth_routes._create_token("operator")
    yield app, app.test_client(), {"Authorization": "Bearer " + token}
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

    _DesktopShutdownRecoveryOwner(app).release(deadline=time.monotonic() + 10)


def test_factory_publishes_shared_owners_without_model_or_source_activation(mounted):
    from flinttrade_core.data_runtime import DataRuntime
    from flinttrade_core.run_adoption import ModelRunServices

    app, client, headers = mounted
    data = app.config.get("DATA_RUNTIME")
    models = app.config.get("MODEL_RUN_SERVICES")
    assert isinstance(data, DataRuntime), "normal factory omitted the data owner"
    assert isinstance(models, ModelRunServices), "normal factory omitted run services"
    assert data.app is models.app is app
    assert app.config["HISTORY_PIPELINE"] is data.history
    assert app.config["ARTIFACT_ACTIVATION"] is models.adoptions
    assert app.config["TRAINING_JOBS"] is models.training
    assert callable(app.config["LEARNING_PERMISSION_RESOLVER"])
    assert app.config["KNOWLEDGE_INSTALLED"] is True
    assert "SERVICE_TASK_DISPATCHER" not in app.config
    assert "LEARNING_CONSENT_LEDGER" not in app.config
    assert data.active_sources == 0
    response = client.get("/api/v1/data/datasets", headers=headers)
    assert response.status_code == 200, response.json
    assert all(item["status"] == "unavailable" for item in response.json["data"]["datasets"])
    assert "SERVICE_TASK_DISPATCHER" not in app.config


def test_factory_history_and_portfolio_reach_the_actual_shared_readers(mounted):
    app, client, headers = mounted
    runtime = app.config.get("DATA_RUNTIME")
    assert runtime is not None, "normal factory omitted shared persistence"
    identity, _, policy, contributors = history_input()
    scope = server_scope(app, headers)
    snapshot = runtime.history.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
    result = app.config["BACKTEST_DATA_CONNECTOR_FACTORY"]().load_manifest(snapshot["snapshot_id"], scope=scope)
    assert result.success
    assert result.manifest == snapshot
    response = client.get("/v1/historify/snapshots/" + snapshot["snapshot_id"], headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["data"] == snapshot
    evidence_url = "/api/v1/data/portfolio/evidence"
    written = client.post(evidence_url, headers=headers, json={"origin": "manual", "source_id": "fixture-ledger", "records": [manual_record()]})
    assert written.status_code == 201, written.json
    read = client.get(evidence_url, headers=headers)
    assert read.status_code == 200, read.json
    assert read.json["data"]["records"][0]["quantity"] == "2.125"
    assert read.json["data"]["execution_authority"] is False


def test_normal_factory_persists_manifest_backtest_and_returns_immutable_receipts(mounted, monkeypatch):
    from flinttrade_backtest.strategies import STRATEGY_REGISTRY
    from flinttrade_core.evaluation import EvaluationStore
    from packages.core.core.tests.test_backtest_manifest_integration import ManifestCandidate

    app, client, headers = mounted
    monkeypatch.setitem(STRATEGY_REGISTRY, "ManifestCandidate", ManifestCandidate)
    monkeypatch.setattr(ManifestCandidate, "observed", [])
    identity, _, policy, contributors = history_input()
    scope = server_scope(app, headers)
    snapshot = app.config["HISTORY_PIPELINE"].publish_history(
        identity=identity, scope=scope, policy=policy, contributors=contributors)
    response = client.post("/api/v1/backtest/run", headers=headers, json={
        "symbol": identity["instrument_id"], "exchange": identity["venue"], "interval": "1m",
        "start_date": snapshot["bars"][0]["timestamp"][:10], "end_date": snapshot["bars"][-1]["timestamp"][:10],
        "strategy": "ManifestCandidate", "initial_capital": 1000,
        "data_manifest_id": snapshot["snapshot_id"],
    })
    assert response.status_code == 200, response.json
    trial_id = response.headers.get("X-Trial-Id")
    experiment_id = response.headers.get("X-Experiment-Id")
    assert trial_id and experiment_id, "normal factory lost immutable backtest custody"
    trial = client.get("/api/v1/backtest/trials/" + trial_id, headers=headers)
    experiment = client.get("/api/v1/backtest/experiments/" + experiment_id, headers=headers)
    assert trial.status_code == experiment.status_code == 200
    assert trial.json["data"]["status"] == "completed"
    assert trial.json["data"]["evidence"]["qualified"] is False
    assert experiment.json["data"]["manifest"]["data"]["manifest_id"] == snapshot["snapshot_id"]
    assert experiment.json["data"]["manifest"]["data"]["scope"] == scope
    results = app.config["BACKTEST_RESULT_STORE"]
    owner = app.config["EVALUATION_STORE"]
    assert owner.path == results.evidence_path
    # The actual persisted authority, not a response-only or test-installed ID.
    reopened = EvaluationStore(results.evidence_path)
    assert reopened.trial(trial_id) == trial.json["data"]
    assert reopened.experiment(experiment_id) == experiment.json["data"]


def test_shared_history_remains_owned_until_actual_download_worker_exits(mounted, monkeypatch):
    import asyncio
    import threading

    from flinttrade_historical.watchlist_routes import _get_job_manager

    app, _, headers = mounted
    runtime = app.config["DATA_RUNTIME"]
    with app.app_context():
        manager = _get_job_manager()
    assert app.config.get("HISTORIFY_JOB_MANAGER") is manager, "download worker has no app-owned lifecycle"
    assert runtime.downloads is manager
    identity, _, policy, contributors = history_input()
    scope = server_scope(app, headers)
    snapshot = runtime.history.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
    connector = runtime.connector()
    entered, release = threading.Event(), threading.Event()
    read_before_worker_exit = []

    async def download(_progress):
        entered.set()
        await asyncio.to_thread(release.wait)
        read_before_worker_exit.append(connector.load_manifest(snapshot["snapshot_id"], scope=scope).success)

    job = manager.start(total=1, runner=download, storage_path=str(runtime.workspace))
    real_close = manager.close
    monkeypatch.setattr(manager, "close", lambda **_kwargs: real_close(timeout=0.01))
    try:
        assert entered.wait(2)
        with pytest.raises(RuntimeError, match="download"):
            runtime.close()
        assert not runtime.closed
        assert app.config["DATA_RUNTIME"] is runtime
        assert connector.load_manifest(snapshot["snapshot_id"], scope=scope).success
        release.set()
        assert real_close(timeout=2)
        runtime.close()
        assert read_before_worker_exit == [True]
        assert manager.get(job.job_id).status == "done"
        assert runtime.closed
        assert not connector.load_manifest(snapshot["snapshot_id"], scope=scope).success
    finally:
        release.set()
        assert real_close(timeout=2)


def test_data_authentication_and_scope_refusals_stay_distinct(mounted):
    app, client, headers = mounted
    path = "/api/v1/data/datasets"
    with app.app_context():
        narrowed = auth_routes._create_token("operator", scopes=("admin.services.read",))
    assert client.get(path, headers={"Authorization": "Bearer " + narrowed}).status_code == 403
    assert client.get(path).status_code == 401
    assert client.post("/v1/auth/logout", headers=headers).status_code == 200
    retired = client.get(path, headers=headers)
    assert retired.status_code == 401, retired.json
    assert retired.json["code"] == "operator_session_required"


def test_model_control_authorisation_is_inside_runtime_request_admission(mounted, monkeypatch):
    app, client, headers = mounted
    owner = app.config["MODEL_RUN_SERVICES"]
    tracker = app.config["RUNTIME_REQUEST_TRACKER"]
    observed = []
    original = owner.authorise

    def observe(*args, **kwargs):
        observed.append(tracker._active)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, "authorise", observe)
    response = client.post("/api/v1/backtest/adoptions", headers=headers, json={
        "request_id": "fixture-guard", "run_id": "unknown-run", "role": "reasoning", "candidate": "unknown-candidate", "expected_generation": 0,
    })
    assert response.status_code == 403, response.json
    assert observed == [1], "model control touched dependencies outside the request drain owner"
    observed.clear()
    app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    unavailable = client.post("/api/v1/backtest/adoptions", headers=headers, json={
        "request_id": "fixture-guard-after-close", "run_id": "unknown-run", "role": "reasoning", "candidate": "unknown-candidate", "expected_generation": 0,
    })
    assert unavailable.status_code == 503
    assert observed == []


def test_factory_model_controls_refuse_generic_keys_and_missing_run_authority(mounted):
    app, client, headers = mounted
    assert app.config.get("MODEL_RUN_SERVICES") is not None
    path = "/api/v1/backtest/training/jobs/unknown-job"
    response = client.get(path, headers={"X-API-Key": os.environ["FLINTTRADE_API_KEY"]})
    assert response.status_code == 403, response.json
    assert response.json["code"] == "operator_session_required"
    assert response.headers["Cache-Control"] == "no-store"
    refused = client.post("/api/v1/backtest/adoptions", headers=headers, json={
        "request_id": "fixture-request", "run_id": "unknown-run", "role": "reasoning", "candidate": "unknown-candidate", "expected_generation": 0,
    })
    assert refused.status_code == 403, refused.json
    assert refused.json["code"] == "run_not_owned"
    assert "SERVICE_TASK_DISPATCHER" not in app.config
