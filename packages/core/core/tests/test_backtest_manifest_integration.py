"""Canonical history reaches the mounted engine and immutable evidence reader."""
from __future__ import annotations

from copy import deepcopy
import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_backtest.base_strategy import BaseBacktestStrategy
from flinttrade_backtest.data_connector import DataConnector
from flinttrade_backtest.strategies import STRATEGY_REGISTRY
from flinttrade_core.evaluation import EvaluationStore
from flinttrade_historical.pipeline import DataPipeline

pytestmark = pytest.mark.integration
HEADERS = {"X-API-Key": "synthetic-manifest-key"}


class ManifestCandidate(BaseBacktestStrategy):
    observed: list[float] = []

    def on_bar(self, bar: Any) -> None:
        """Observe the real engine input without introducing a trading baseline."""
        self.observed.append(float(bar.close))


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_API_KEY", HEADERS["X-API-Key"])
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    monkeypatch.setitem(STRATEGY_REGISTRY, "ManifestCandidate", ManifestCandidate)
    monkeypatch.setattr(ManifestCandidate, "observed", [])
    scope = {"principal_id": "synthetic-operator", "environment": "research", "account_id": None,
             "run_id": "synthetic-research-run", "generation": 1}
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
                              "environment": "research", "account_id": None, "auth_generation": 1,
                              "configuration_generation": 1},
                   "bars": [{"timestamp": f"2026-01-05T14:{30 + i}:00+00:00", "open": 100,
                             "high": 103, "low": 99, "close": 100 + i, "volume": 0.5,
                             "oi": None, "published_at": None} for i in range(3)]}
    path = str(tmp_path / "history.duckdb")
    with DataPipeline(path) as pipeline:
        snapshot = pipeline.publish_history(identity=identity, scope=scope, policy=policy, contributors=[contributor])

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    # Installed evidence reads require a real full operator session, not the
    # generic compatibility API key accepted by legacy evaluation callers.
    from flinttrade_core import auth_routes

    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.invalid", secrets.token_urlsafe(32))
    with app.app_context():
        token = auth_routes._create_token("operator")
    monkeypatch.delitem(HEADERS, "X-API-Key")
    monkeypatch.setitem(HEADERS, "Authorization", "Bearer " + token)
    app.config.update(TESTING=True, DATA_SCOPE_RESOLVER=lambda: deepcopy(scope),
                      BACKTEST_DATA_CONNECTOR_FACTORY=lambda: DataConnector(path),
                      EVALUATION_STORE=EvaluationStore(tmp_path / "evaluation.sqlite"))
    legacy_calls = []

    def forbid_legacy(*args, **kwargs):
        legacy_calls.append(True)
        raise AssertionError("An explicit manifest cannot invoke the legacy loader")

    monkeypatch.setattr(DataConnector, "load", forbid_legacy)
    body = {"symbol": "TEST", "exchange": "XNAS", "interval": "1m", "start_date": "2026-01-05",
            "end_date": "2026-01-05", "strategy": "ManifestCandidate", "initial_capital": 1000,
            "data_manifest_id": snapshot["snapshot_id"]}
    try:
        yield SimpleNamespace(app=app, client=app.test_client(), scope=scope, snapshot=snapshot, path=path,
                              body=body, legacy_calls=legacy_calls, identity=identity, policy=policy,
                              contributor=contributor)
    finally:
        for key in ("MODEL_RUN_SERVICES", "DATA_RUNTIME", "LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME", "SERVICE_TASK_DISPATCHER"):
            owner = app.config.pop(key, None)
            if owner is not None:
                owner.close()


def test_selected_manifest_reaches_real_engine_and_immutable_experiment(mounted):
    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS, json=mounted.body)
    assert response.status_code == 200, response.get_json()
    assert ManifestCandidate.observed == [100.0, 101.0, 102.0]
    assert mounted.legacy_calls == []
    trial = mounted.client.get(f"/api/v1/backtest/trials/{response.headers['X-Trial-Id']}", headers=HEADERS)
    assert trial.status_code == 200
    assert trial.json["data"]["status"] == "completed"
    assert trial.json["data"]["evidence"]["qualified"] is False
    experiment = mounted.client.get(
        f"/api/v1/backtest/experiments/{response.headers['X-Experiment-Id']}", headers=HEADERS,
    )
    assert experiment.status_code == 200
    data = experiment.json["data"]["manifest"]["data"]
    assert data["manifest_id"] == mounted.snapshot["snapshot_id"]
    assert data["identity"] == mounted.identity
    assert data["scope"] == mounted.scope
    assert data["coverage"] == mounted.snapshot["coverage"]
    assert data["provenance_status"] == "available"
    assert data["rights"] == "not_attested"


def test_shipped_builtin_keeps_actual_source_identity_in_immutable_receipt(mounted):
    import hashlib
    import inspect

    from flinttrade_backtest.strategies import BUILTIN_STRATEGIES

    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS,
                                   json={**mounted.body, "strategy": "EMACrossover"})
    assert response.status_code == 200, response.json
    assert response.json["data"]["total_bars"] == 3
    assert mounted.legacy_calls == []
    trial = mounted.client.get(f"/api/v1/backtest/trials/{response.headers['X-Trial-Id']}", headers=HEADERS)
    assert trial.status_code == 200, trial.json
    assert trial.json["data"]["status"] == "completed"
    assert trial.json["data"]["evidence"]["qualified"] is False
    experiment = mounted.client.get(
        f"/api/v1/backtest/experiments/{response.headers['X-Experiment-Id']}", headers=HEADERS)
    assert experiment.status_code == 200, experiment.json
    manifest = experiment.json["data"]["manifest"]
    assert manifest["data"]["manifest_id"] == mounted.snapshot["snapshot_id"]
    assert manifest["strategy"] == {"name": "EMACrossover", "source_digest": hashlib.sha256(
        inspect.getsource(BUILTIN_STRATEGIES["EMACrossover"]).encode()).hexdigest()}


def test_manifest_trial_and_experiment_readback_require_current_exact_scope(mounted):
    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS, json=mounted.body)
    assert response.status_code == 200
    mounted.scope["principal_id"] = "another-synthetic-operator"
    for resource, header in (("trials", "X-Trial-Id"), ("experiments", "X-Experiment-Id")):
        denied = mounted.client.get(f"/api/v1/backtest/{resource}/{response.headers[header]}", headers=HEADERS)
        assert denied.status_code == 403
        assert "manifest_id" not in denied.get_data(as_text=True)
        assert "synthetic-research-run" not in denied.get_data(as_text=True)


@pytest.mark.parametrize("change", [
    {"symbol": "OTHER"}, {"exchange": "NSE"}, {"interval": "5m"},
    {"start_date": "2026-01-04"}, {"end_date": "2026-01-06"}, {"symbol": " TEST "},
    {"scope": {"principal_id": "client-asserted"}},
])
def test_manifest_cannot_be_relabelled_or_given_client_authority(mounted, change):
    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS, json={**mounted.body, **change})
    assert response.status_code == 400, response.get_json()
    assert ManifestCandidate.observed == []
    assert mounted.legacy_calls == []
    assert "X-Trial-Id" not in response.headers


@pytest.mark.parametrize("field", ["snapshot_id", "scope"])
def test_manifest_loader_cannot_substitute_another_identity(mounted, monkeypatch, field):
    load = DataConnector.load_manifest

    def substituted(self, identity, *, scope):
        result = load(self, identity, scope=scope)
        assert result.success
        if field == "snapshot_id":
            result.manifest[field] = "0" * 64
        else:
            result.manifest[field] = {**scope, "generation": scope["generation"] + 1}
        return result

    monkeypatch.setattr(DataConnector, "load_manifest", substituted)
    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS, json=mounted.body)
    assert response.status_code == 400
    assert ManifestCandidate.observed == []
    assert mounted.legacy_calls == []


@pytest.mark.parametrize("value", [None, True, 123, "a" * 63, "A" * 64, "../snapshot"])
def test_invalid_manifest_token_refuses_before_data_owner(mounted, value):
    called = []

    def forbidden_factory():
        called.append(True)
        raise AssertionError("Invalid input reached the data owner")

    mounted.app.config["BACKTEST_DATA_CONNECTOR_FACTORY"] = forbidden_factory
    response = mounted.client.post(
        "/api/v1/backtest/run", headers=HEADERS, json={**mounted.body, "data_manifest_id": value},
    )
    assert response.status_code == 400
    assert called == []


@pytest.mark.parametrize("raw", ["null", "[]", "[1]", "false", "{broken"])
def test_nonobject_and_malformed_backtest_requests_cannot_load_data(mounted, raw):
    response = mounted.client.post(
        "/api/v1/backtest/run", headers=HEADERS, data=raw, content_type="application/json",
    )
    assert response.status_code == 400
    assert ManifestCandidate.observed == []
    assert mounted.legacy_calls == []


@pytest.mark.parametrize("fault", ["partial", "corrupt", "retired-scope", "unconfigured"])
def test_unavailable_manifest_never_falls_back_or_creates_a_successful_trial(mounted, fault):
    expected = 400
    if fault == "partial":
        contribution = deepcopy(mounted.contributor)
        contribution["bars"].pop()
        with DataPipeline(mounted.path) as pipeline:
            partial = pipeline.publish_history(identity=mounted.identity, scope=mounted.scope,
                                               policy=mounted.policy, contributors=[contribution])
        mounted.body["data_manifest_id"] = partial["snapshot_id"]
    elif fault == "corrupt":
        with DataPipeline(mounted.path) as pipeline:
            pipeline.connection.execute("UPDATE history_manifests SET document='{}'")
    elif fault == "retired-scope":
        mounted.scope["generation"] += 1
    else:
        mounted.app.config.pop("DATA_SCOPE_RESOLVER")
        expected = 503
    response = mounted.client.post("/api/v1/backtest/run", headers=HEADERS, json=mounted.body)
    assert response.status_code == expected
    assert ManifestCandidate.observed == []
    assert mounted.legacy_calls == []
    assert "X-Trial-Id" not in response.headers
