"""Mounted backtests bind only a server-owned explicitly selected run."""
from __future__ import annotations

import secrets
from types import SimpleNamespace

import pytest

from flinttrade_backtest.data_connector import DataConnector
from flinttrade_backtest.strategies import STRATEGY_REGISTRY

from packages.core.core.tests.test_backtest_manifest_integration import ManifestCandidate
from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted

pytestmark = pytest.mark.integration


@pytest.fixture
def scoped_backtest(composed, monkeypatch):
    owner, supervisor, app, client, _store, calls, headers, desk = composed
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.invalid", secrets.token_urlsafe(32))
    operator_id, epoch = app.config["AUTH_SERVICE"].current_session_binding()
    headers = {"Authorization": "Bearer " + desk.token(oid=operator_id, epoch=epoch,
               scopes=["admin.services.read", "admin.services.write", "admin.accounts.read"])}
    run_id = supervisor.run.run_id
    owner.configure_access(run_id, actor=desk.owner, operations=["evaluation.read"],
                           valid_until=owner.now() + 3600, evidence="synthetic-run-evidence-access",
                           expected_revision=0)
    with app.test_request_context("/api/v1/backtest/run", method="POST", headers=headers):
        scope = app.config["DATA_SCOPE_RESOLVER"]()
    identity = {"instrument_id": "TEST", "venue": "XNAS", "asset_class": "equity", "currency": "USD",
                "quantity_unit": "shares", "price_unit": "currency_per_share", "multiplier": "1",
                "interval_seconds": 60, "adjustment": "raw", "calendar_id": "synthetic-session",
                "calendar_revision": "fixture-v1"}
    policy = {"mode": "single", "priority": ["synthetic-source"], "duplicates": "identical_only",
              "conflicts": "reject", "revision": "synthetic-policy-v1",
              "sessions": [{"start": "2026-01-05T14:30:00+00:00", "end": "2026-01-05T14:33:00+00:00"}]}
    contributor = {"identity": identity, "revision": "fixture-v1", "status": "available",
                   "retrieved_at": "2026-01-05T15:00:00+00:00",
                   "source": {"connection_id": "synthetic-source", "provider": "inert",
                              "environment": scope["environment"], "account_id": scope["account_id"],
                              "auth_generation": 1, "configuration_generation": 1},
                   "bars": [{"timestamp": f"2026-01-05T14:{30 + i}:00+00:00", "open": 100,
                             "high": 103, "low": 99, "close": 100 + i, "volume": 1,
                             "oi": None, "published_at": None} for i in range(3)]}
    snapshot = app.config["DATA_RUNTIME"].history.publish_history(
        identity=identity, scope=scope, policy=policy, contributors=[contributor])
    monkeypatch.setitem(STRATEGY_REGISTRY, "ManifestCandidate", ManifestCandidate)
    monkeypatch.setattr(ManifestCandidate, "observed", [])
    loads = []
    connector_factory = app.config["BACKTEST_DATA_CONNECTOR_FACTORY"]

    def factory():
        loads.append("canonical-history")
        return connector_factory()

    app.config["BACKTEST_DATA_CONNECTOR_FACTORY"] = factory
    body = {"symbol": "TEST", "exchange": "XNAS", "interval": "1m", "start_date": "2026-01-05",
            "end_date": "2026-01-05", "strategy": "ManifestCandidate", "initial_capital": 1000,
            "data_manifest_id": snapshot["snapshot_id"], "run_id": run_id}
    try:
        yield SimpleNamespace(owner=owner, supervisor=supervisor, app=app, client=client, calls=calls,
                              headers=headers, desk=desk, body=body, scope=scope, loads=loads)
    finally:
        from flinttrade_core.practice_agent_runtime import shutdown_practice_agent

        assert shutdown_practice_agent(app, timeout=5), "Retain data while the actual worker drains"
        app.config["DATA_RUNTIME"].close()


def test_selected_run_is_server_derived_in_actual_immutable_backtest_receipt(scoped_backtest):
    f = scoped_backtest
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert response.status_code == 200, response.json
    assert ManifestCandidate.observed == [100.0, 101.0, 102.0]
    experiment_id, trial_id = response.headers["X-Experiment-Id"], response.headers["X-Trial-Id"]
    experiment = f.client.get("/api/v1/backtest/experiments/" + experiment_id, headers=f.headers)
    assert experiment.status_code == 200, experiment.json
    manifest = experiment.json["data"]["manifest"]
    assert manifest["control_scope"] == vars(f.owner.runs.scope(f.body["run_id"]))
    assert manifest["data"]["scope"] == f.scope
    assert manifest["data"]["manifest_id"] == f.body["data_manifest_id"]
    trial = f.client.get("/api/v1/backtest/trials/" + trial_id, headers=f.headers)
    assert trial.status_code == 200, trial.json
    assert trial.json["data"]["evidence"]["qualified"] is False
    assert f.calls == [], "Attaching evidence is not model inference or trading"


@pytest.mark.parametrize("run_id", [None, True, 123, "", "../run", " run ", "x" * 129])
def test_invalid_selector_is_not_normalised_or_sent_to_data(scoped_backtest, run_id):
    f = scoped_backtest
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json={**f.body, "run_id": run_id})
    assert response.status_code == 400
    assert f.loads == []
    assert "X-Trial-Id" not in response.headers


@pytest.mark.parametrize("field", ["scope", "control_scope", "actor", "account", "environment"])
def test_body_authority_never_labels_scoped_or_legacy_evidence(scoped_backtest, field):
    f = scoped_backtest
    for body in (f.body, {k: v for k, v in f.body.items() if k not in {"run_id", "data_manifest_id"}}):
        response = f.client.post("/api/v1/backtest/run", headers=f.headers, json={**body, field: "forged"})
        assert response.status_code == 400
        assert f.loads == []
        assert "X-Trial-Id" not in response.headers


@pytest.mark.parametrize("change", ["actor", "api-key", "origin", "cross-site", "unknown-run", "access"])
def test_scoped_backtest_requires_current_full_operator_and_owned_read_access(scoped_backtest, change):
    f = scoped_backtest
    headers, body = dict(f.headers), dict(f.body)
    if change == "actor":
        headers = {"Authorization": "Bearer " + f.desk.token(sub="foreign-operator",
                   scopes=["admin.services.read", "admin.services.write"])}
    elif change == "api-key":
        headers = {"X-API-Key": "synthetic-key"}
    elif change == "origin":
        headers["Origin"] = "https://foreign.invalid"
    elif change == "cross-site":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif change == "unknown-run":
        body["run_id"] = "unregistered-run"
    else:
        f.owner.configure_access(body["run_id"], actor=f.desk.owner, operations=[],
                                 valid_until=f.owner.now() + 3600, evidence="synthetic-revocation",
                                 expected_revision=1)
    response = f.client.post("/api/v1/backtest/run", headers=headers, json=body)
    assert response.status_code == 403, response.json
    assert f.loads == []
    assert "X-Trial-Id" not in response.headers


@pytest.mark.parametrize("change", ["access", "session", "evidence-missing", "evidence-replaced", "data-scope"])
def test_publication_revalidates_authority_after_actual_history_read(scoped_backtest, monkeypatch, tmp_path, change):
    from flinttrade_core.evaluation import EvaluationStore
    f = scoped_backtest
    original = DataConnector.load_manifest
    store = f.app.config["EVALUATION_STORE"]

    def changed(self, *args, **kwargs):
        data = original(self, *args, **kwargs)
        assert data.success
        if change == "access":
            f.owner.configure_access(f.body["run_id"], actor=f.desk.owner, operations=[],
                                     valid_until=f.owner.now() + 3600, evidence="synthetic-revocation",
                                     expected_revision=1)
        elif change == "session":
            f.desk.revoked.add("practice-session")
        elif change == "evidence-missing":
            monkeypatch.delitem(f.app.config, "EVALUATION_STORE")
            monkeypatch.delitem(f.app.config, "BACKTEST_RESULT_STORE")
        elif change == "evidence-replaced":
            monkeypatch.setitem(f.app.config, "EVALUATION_STORE", EvaluationStore(tmp_path / "replacement.sqlite"))
        else:
            monkeypatch.setitem(f.app.config, "DATA_SCOPE_RESOLVER", lambda: {**f.scope, "generation": f.scope["generation"] + 1})
        return data

    monkeypatch.setattr(DataConnector, "load_manifest", changed)
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert response.status_code == (503 if change.startswith("evidence-") else 403), response.json
    assert ManifestCandidate.observed == []
    assert "X-Trial-Id" not in response.headers
    with store._db() as db:
        assert db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0


def test_scoped_store_failure_is_not_mislabelled_as_operator_refusal(scoped_backtest, monkeypatch):
    f = scoped_backtest

    def failure(_manifest):
        raise ValueError("synthetic immutable-store failure")

    monkeypatch.setattr(f.app.config["EVALUATION_STORE"], "create", failure)
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert response.status_code == 500, response.json
    assert "X-Trial-Id" not in response.headers
    assert ManifestCandidate.observed == []


def test_engine_authorisation_exception_still_finishes_failed_trial(scoped_backtest, monkeypatch):
    from flinttrade_core import backtest_routes
    from flinttrade_core.model_control_auth import ModelControlDenied
    f = scoped_backtest

    def failure(*_args):
        raise ModelControlDenied("synthetic engine failure")

    monkeypatch.setattr(backtest_routes, "_run_registry_backtest", failure)
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert response.status_code == 500, response.json
    trial = f.app.config["EVALUATION_STORE"].trial(response.headers["X-Trial-Id"])
    assert trial["status"] == "failed"
    assert trial["evidence"]["stage"] == "simulation"


@pytest.mark.parametrize("change", ["access", "data-scope", "evidence-replaced"])
def test_completed_evidence_is_retained_but_retired_authority_gets_no_result(scoped_backtest, monkeypatch, tmp_path, change):
    from flinttrade_core import backtest_routes
    from flinttrade_core.evaluation import EvaluationStore
    f = scoped_backtest
    original = backtest_routes._run_registry_backtest
    store = f.app.config["EVALUATION_STORE"]

    def retire_after_compute(*args):
        result = original(*args)
        if change == "access":
            f.owner.configure_access(f.body["run_id"], actor=f.desk.owner, operations=[],
                                     valid_until=f.owner.now() + 3600, evidence="synthetic-post-compute-revocation",
                                     expected_revision=1)
        elif change == "data-scope":
            monkeypatch.setitem(f.app.config, "DATA_SCOPE_RESOLVER", lambda: {**f.scope, "generation": f.scope["generation"] + 1})
        else:
            monkeypatch.setitem(f.app.config, "EVALUATION_STORE", EvaluationStore(tmp_path / "after-compute.sqlite"))
        return result

    monkeypatch.setattr(backtest_routes, "_run_registry_backtest", retire_after_compute)
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert response.status_code == (503 if change == "evidence-replaced" else 403), response.json
    assert "data" not in response.json
    assert ManifestCandidate.observed == [100.0, 101.0, 102.0]
    trial = store.trial(response.headers["X-Trial-Id"])
    assert trial["status"] == "completed"
    assert trial["evidence"]["qualified"] is False


@pytest.mark.parametrize("change", ["none", "access", "session", "data-scope", "evidence-replaced"])
@pytest.mark.parametrize("save_fault", [False, True])
def test_final_authority_check_follows_real_compatibility_save(scoped_backtest, monkeypatch, tmp_path, change, save_fault):
    from flinttrade_core.evaluation import EvaluationStore
    f = scoped_backtest
    saved = []
    evidence = f.app.config["EVALUATION_STORE"]
    compatibility = f.app.config["BACKTEST_RESULT_STORE"]
    original = compatibility.save

    def save_then_change(*args, **kwargs):
        receipt = original(*args, **kwargs)
        assert receipt, "Keep the actual compatibility-store write"
        saved.append(receipt)
        if change == "access":
            f.owner.configure_access(f.body["run_id"], actor=f.desk.owner, operations=[],
                                     valid_until=f.owner.now() + 3600, evidence="synthetic-after-save-revocation",
                                     expected_revision=1)
        elif change == "session":
            f.desk.revoked.add("practice-session")
        elif change == "data-scope":
            monkeypatch.setitem(f.app.config, "DATA_SCOPE_RESOLVER", lambda: {**f.scope, "generation": f.scope["generation"] + 1})
        elif change == "evidence-replaced":
            monkeypatch.setitem(f.app.config, "EVALUATION_STORE", EvaluationStore(tmp_path / "after-save.sqlite"))
        if save_fault:
            raise RuntimeError("synthetic late compatibility-save failure")
        return receipt

    monkeypatch.setattr(compatibility, "save", save_then_change)
    response = f.client.post("/api/v1/backtest/run", headers=f.headers, json=f.body)
    assert len(saved) == 1
    assert compatibility.latest(f.body["strategy"]) is not None
    trial = evidence.trial(response.headers["X-Trial-Id"])
    assert trial["status"] == "completed"
    assert trial["evidence"]["qualified"] is False
    if change == "none":
        assert response.status_code == 200, response.json
        assert response.json["data"]["total_bars"] == 3
    else:
        assert response.status_code == (503 if change == "evidence-replaced" else 403), response.json
        assert "data" not in response.json
