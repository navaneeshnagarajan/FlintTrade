"""Normal-factory shared-data flows with real stores and no external transport."""
from __future__ import annotations

import importlib.util
import secrets

import pytest

from flinttrade_core import auth_routes
from packages.core.historical.tests.test_history_manifest import history_input

pytestmark = pytest.mark.integration


def install(app, workspace):
    assert importlib.util.find_spec("flinttrade_core.data_runtime") is not None, "data runtime installer missing"
    from flinttrade_core.data_runtime import install_data_runtime
    install_data_runtime(app, workspace)
    return app.config["DATA_RUNTIME"]


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
    headers = {"Authorization": "Bearer " + token}
    yield app, app.test_client(), tmp_path, headers
    runtime = app.config.get("DATA_RUNTIME")
    if runtime:
        runtime.close()


def server_scope(app, headers):
    with app.test_request_context(headers=headers):
        return app.config["DATA_SCOPE_RESOLVER"]()


def test_installer_failed_history_path_releases_secure_portfolio_custody(tmp_path, monkeypatch):
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.secure_file import HeldOwnerDirectory

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", secrets.token_urlsafe(32))
    not_directory = tmp_path / "not-a-directory"
    not_directory.write_text("fixture")
    monkeypatch.setenv("DUCKDB_PATH", str(not_directory / "flint.duckdb"))
    opened = []
    original = HeldOwnerDirectory.__enter__
    def observe(self):
        result = original(self)
        if self.path == tmp_path / "portfolio-evidence":
            opened.append(self)
        return result
    monkeypatch.setattr(HeldOwnerDirectory, "__enter__", observe)
    # Inject before normal factory construction, not after its idempotent mount.
    with pytest.raises(OSError):
        create_flask_app()
    assert len(opened) == 1
    for directory in opened:
        with pytest.raises(OSError, match="closed"):
            directory.revalidate()


def test_normal_factory_installer_shares_history_with_connector_and_http(mounted):
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    assert install(app, workspace) is runtime
    scope = server_scope(app, headers)
    assert scope["account_id"] is None
    assert scope["run_id"] is None
    assert scope["environment"] == "local_history"
    assert scope["generation"] == app.config["AUTH_SERVICE"].current_session_binding()[1]
    identity, _, policy, contributors = history_input()
    snapshot = runtime.history.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
    connector = app.config["BACKTEST_DATA_CONNECTOR_FACTORY"]()
    result = connector.load_manifest(snapshot["snapshot_id"], scope=scope)
    assert result.success
    assert result.manifest == snapshot
    response = client.get("/v1/historify/snapshots/" + snapshot["snapshot_id"], headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["data"] == snapshot
    assert not connector.load_manifest(snapshot["snapshot_id"], scope={**scope, "generation": scope["generation"] + 1}).success
    assert client.get("/v1/historify/snapshots/" + snapshot["snapshot_id"]).status_code == 401


def manual_record():
    return {"record_id": "declared-1", "kind": "holding", "instrument_id": "declared-fund",
            "venue": "manual", "currency": "INR", "quantity_unit": "units", "quantity": "2.125",
            "observed_at": "2026-01-05T15:00:00+00:00"}


def test_http_datasets_share_real_history_acquisition_and_retire_on_logout(mounted, monkeypatch):
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    identity, _, policy, contributors = history_input()
    snapshot = runtime.history.publish_history(identity=identity, scope=server_scope(app, headers),
                                              policy=policy, contributors=contributors)
    catalogue = client.get("/api/v1/data/datasets", headers=headers)
    assert catalogue.status_code == 200, catalogue.json
    datasets = catalogue.json["data"]["datasets"]
    historical = next(row for row in datasets if row.get("snapshot_id") == snapshot["snapshot_id"])
    assert historical["source_kind"] == "recorded_history"
    assert historical["execution_authority"] is False
    assert all(row["status"] == "unavailable" for row in datasets if row["source_kind"] == "native")
    url = "/api/v1/data/leases"
    dataset_id = historical["dataset_id"]
    first = client.post(url, headers=headers, json={"dataset_id": dataset_id})
    second = client.post(url, headers=headers, json={"dataset_id": dataset_id})
    assert first.status_code == second.status_code == 201, (first.json, second.json)
    assert first.json["data"]["snapshot"]["payload"] == snapshot
    assert runtime.acquisition.diagnostics()["active_acquisitions"] == 1
    lease1, lease2 = first.json["data"]["lease_id"], second.json["data"]["lease_id"]
    assert client.get(url + "/" + lease1, headers=headers).json["data"]["dataset_id"] == dataset_id
    assert client.delete(url + "/" + lease1, headers=headers).json["data"]["released"]
    assert runtime.acquisition.diagnostics()["active_acquisitions"] == 1
    assert client.delete(url + "/" + lease2, headers=headers).json["data"]["released"]
    assert runtime.acquisition.diagnostics()["active_acquisitions"] == 0
    assert client.post(url, headers=headers, json={"dataset_id": dataset_id, "generation": 99}).status_code == 400
    third = client.post(url, headers=headers, json={"dataset_id": dataset_id})
    assert third.status_code == 201
    assert client.post("/v1/auth/logout", headers=headers).status_code == 200
    # The owner performs actual periodic revocation, even with no subsequent data requests.
    import time
    deadline = time.monotonic() + 3
    while runtime.active_sources and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runtime.active_sources == 0
    assert client.get(url + "/" + third.json["data"]["lease_id"], headers=headers).status_code == 401


def test_manual_evidence_survives_reopen_without_broker_or_write_from_read_scope(mounted):
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    url = "/api/v1/data/portfolio/evidence"
    body = {"origin": "manual", "source_id": "operator-notes", "records": [manual_record()]}
    with app.app_context():
        narrowed = auth_routes._create_token("operator", scopes=("admin.accounts.read",))
    assert client.post(url, headers={"Authorization": "Bearer " + narrowed}, json=body).status_code == 403
    written = client.post(url, headers=headers, json=body)
    assert written.status_code == 201, written.json
    facts = client.get(url, headers=headers)
    assert facts.status_code == 200, facts.json
    assert facts.json["data"]["records"][0]["quantity"] == "2.125"
    assert facts.json["data"]["scope"]["environment"] == "manual_ledger"
    assert facts.json["data"]["scope"]["account_id"].startswith("manual:")
    assert facts.json["data"]["execution_authority"] is False
    runtime.close()
    from flinttrade_core.data_runtime import DataRuntime
    reopened = DataRuntime(app, workspace)
    try:
        with app.test_request_context(url, headers=headers):
            assert reopened.portfolio.read(reopened.scope()) == facts.json["data"]
    finally:
        reopened.close()


@pytest.mark.parametrize("fault", ["missing", "corrupt", "schema", "symlink", "checksum", "scope"])
def test_established_portfolio_store_is_never_recreated(mounted, fault):
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    url = "/api/v1/data/portfolio/evidence"
    assert client.post(url, headers=headers, json={"origin": "manual", "source_id": "notes",
                                                "records": [manual_record()]}).status_code == 201
    path = runtime.portfolio.path
    runtime.close()
    if fault == "missing":
        path.unlink()
    elif fault == "corrupt":
        path.write_bytes(b"not a database")
    elif fault == "symlink":
        path.rename(path.with_suffix(".original"))
        path.symlink_to(path.with_suffix(".original"))
    else:
        import sqlite3
        with sqlite3.connect(path) as connection:
            if fault == "checksum":
                connection.execute("UPDATE portfolio_evidence SET record_hash='broken'")
            elif fault == "scope":
                connection.execute("UPDATE portfolio_evidence SET scope_id='another-principal'")
            else:
                connection.execute("DROP TABLE portfolio_evidence")
    from flinttrade_core.data_runtime import DataRuntime
    with pytest.raises(Exception):
        DataRuntime(app, workspace)
    if fault == "missing":
        assert not path.exists()
    elif fault == "corrupt":
        assert path.read_bytes() == b"not a database"


def test_shared_pipeline_is_borrowed_by_cache_and_closes_permanently(mounted):
    from flinttrade_historical.cache import OHLCVCache
    app, _, workspace, headers = mounted
    runtime = install(app, workspace)
    with app.app_context():
        cache = OHLCVCache()
        assert cache.pipeline is runtime.history
        cache.initialise()
        cache.close()
    identity, _, policy, contributors = history_input()
    scope = server_scope(app, headers)
    snapshot = runtime.history.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
    connector = runtime.connector()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: connector.load_manifest(snapshot["snapshot_id"], scope=scope), range(24)))
    assert all(item.success and item.manifest == snapshot for item in results)
    runtime.close()
    assert not connector.load_manifest(snapshot["snapshot_id"], scope=scope).success


@pytest.mark.parametrize("body", ["null", "[]", "true", "{", "duplicate"])
def test_evidence_invalid_json_has_no_writes(mounted, body):
    app, client, workspace, headers = mounted
    install(app, workspace)
    url = "/api/v1/data/portfolio/evidence"
    if body == "duplicate":
        import json
        body = '{"origin":"manual","origin":"manual","source_id":"x","records":' + json.dumps([manual_record()]) + '}'
    before = client.get(url, headers=headers).json
    response = client.post(url, data=body, content_type="application/json", headers=headers)
    assert response.status_code in {400, 422}
    assert client.get(url, headers=headers).json == before


def test_csv_import_and_current_principal_readback_never_adopt_request_scope(mounted):
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    import csv
    import io
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(manual_record()))
    writer.writeheader()
    writer.writerow(manual_record())
    url = "/api/v1/data/portfolio/evidence"
    body = {"origin": "statement_csv", "source_id": "declared-statement", "csv": stream.getvalue()}
    result = client.post(url, headers=headers, json=body)
    assert result.status_code == 201, result.json
    assert client.get(url, headers=headers).json["data"]["records"][0]["origin"] == "statement_csv"
    with app.app_context():
        different = auth_routes._create_token("different-principal")
    other = {"Authorization": "Bearer " + different}
    assert client.get(url, headers=other).json["data"]["records"] == []
    assert client.post(url, headers=headers, json={**body, "scope": server_scope(app, headers)}).status_code == 422
    assert client.post(url, headers={**headers, "X-FlintTrade-Token": different}, json=body).status_code == 401
    assert client.post(url, headers={**headers, "Origin": "https://outside.example.invalid"}, json=body).status_code == 403
    # Independent manual facts are not adopted into an older or another generation.
    with app.test_request_context(url, headers=headers):
        scope = runtime.scope()
    assert runtime.portfolio.read({**scope, "generation": scope["generation"] + 1})["records"] == []


def test_watchlist_download_borrows_history_and_reports_frozen_source(mounted, monkeypatch):
    import time
    from flinttrade_historical import watchlist_routes
    from flinttrade_historical.historify import HistorifyDownloader
    from flinttrade_historical.historify_jobs import HistorifyJobManager
    from flinttrade_historical.watchlist import DownloadWatchlist
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    monkeypatch.setattr(watchlist_routes, "_watchlist", DownloadWatchlist(workspace / "fixture-watchlist.sqlite"))
    monkeypatch.setattr(watchlist_routes, "_job_manager", HistorifyJobManager())
    used = []
    original = HistorifyDownloader.__init__
    def observe(self, broker_client, storage, *args, **kwargs):
        used.append(storage)
        original(self, broker_client, storage, *args, **kwargs)
    monkeypatch.setattr(HistorifyDownloader, "__init__", observe)
    added = client.post("/v1/historify/watchlist", headers=headers,
                        json={"symbol": "TCS", "exchange": "NSE", "interval": "1m"})
    assert added.status_code == 201, added.json
    response = client.post("/v1/historify/download", headers=headers,
                           json={"start_date": "2026-01-05", "end_date": "2026-01-05"})
    assert response.status_code == 202, response.json
    identifier = response.json["data"]["job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/v1/historify/download/status", query_string={"job_id": identifier}, headers=headers)
        if job.json["data"]["status"] in {"done", "error", "aborted", "refused"}:
            break
        time.sleep(0.02)
    assert used == [runtime.history]
    assert job.json["data"]["status"] == "error", job.json


def test_legacy_local_bars_are_labelled_and_manifest_runs_use_installed_factory(mounted, monkeypatch):
    from flinttrade_backtest.strategies import STRATEGY_REGISTRY
    from packages.core.core.tests.test_backtest_manifest_integration import ManifestCandidate
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    monkeypatch.setitem(STRATEGY_REGISTRY, "ManifestCandidate", ManifestCandidate)
    monkeypatch.setattr(ManifestCandidate, "observed", [])
    # The parent mounts evaluation custody separately from the data installer.
    from flinttrade_core.evaluation import EvaluationStore
    app.config["EVALUATION_STORE"] = EvaluationStore(workspace / "evaluation.sqlite")
    identity, _, policy, contributors = history_input()
    identity["instrument_id"] = "TEST"
    for part in contributors:
        part["identity"] = identity
    snapshot = runtime.history.publish_history(identity=identity, scope=server_scope(app, headers),
                                              policy=policy, contributors=contributors)
    runtime.history.initialise()
    runtime.history.store_bars("ohlcv_1m", "TEST", "XNAS", snapshot["bars"])
    response = client.get("/v1/historify/bars", headers=headers,
                          query_string={"symbol": "TEST", "exchange": "XNAS", "interval": "1m"})
    assert response.status_code == 200, response.json
    assert response.json["data"]["provenance_status"] == "unqualified_legacy"
    assert response.json["data"]["execution_authority"] is False
    run = client.post("/api/v1/backtest/run", headers=headers, json={
        "symbol": "TEST", "exchange": "XNAS", "interval": "1m", "strategy": "ManifestCandidate",
        "initial_capital": 1000, "data_manifest_id": snapshot["snapshot_id"]})
    assert run.status_code == 200, run.json
    evidence = client.get("/api/v1/backtest/experiments/" + run.headers["X-Experiment-Id"], headers=headers)
    assert evidence.status_code == 200, evidence.json
    assert evidence.json["data"]["manifest"]["data"]["scope"] == server_scope(app, headers)


def test_runtime_expiry_releases_real_history_without_another_read(mounted, monkeypatch):
    import time
    app, client, workspace, headers = mounted
    runtime = install(app, workspace)
    identity, _, policy, contributors = history_input()
    snapshot = runtime.history.publish_history(identity=identity, scope=server_scope(app, headers),
                                              policy=policy, contributors=contributors)
    response = client.post("/api/v1/data/leases", headers=headers,
                           json={"dataset_id": "history:" + snapshot["snapshot_id"]})
    assert response.status_code == 201
    assert runtime.active_sources == 1
    clock = runtime.acquisition._clock
    monkeypatch.setattr(runtime.acquisition, "_clock", lambda: clock() + 61)
    deadline = time.monotonic() + 3
    while runtime.active_sources and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runtime.active_sources == 0


def test_cache_and_manifest_consumers_do_not_share_a_racing_result_cursor(mounted):
    from concurrent.futures import ThreadPoolExecutor
    from flinttrade_historical.cache import OHLCVCache
    app, _, workspace, headers = mounted
    runtime = install(app, workspace)
    with app.app_context():
        cache = OHLCVCache()
        cache.initialise()
    runtime.history.connection.execute("INSERT INTO _cache_meta VALUES ('TEST','XNAS','1m',NULL,NULL,'fixture')")
    identity, _, policy, contributors = history_input()
    scope = server_scope(app, headers)
    snapshot = runtime.history.publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
    connector = runtime.connector()
    def consume(index):
        if index % 2:
            entry = cache.get_entry("TEST", "XNAS", "1m")
            assert entry is not None and entry.symbol == "TEST" and entry.provider == "fixture"
        else:
            assert connector.load_manifest(snapshot["snapshot_id"], scope=scope).success
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(consume, range(200)))
