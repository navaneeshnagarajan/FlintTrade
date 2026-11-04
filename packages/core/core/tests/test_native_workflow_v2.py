"""Normal-factory native-v2 controls with labelled inert broker transport.

Real workspace, credential, registry, read, execution and authentication owners
are retained. These fixtures neither assert production eligibility nor replace
an application factory or its custody lifecycle.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.workspace_migrations import compare_and_swap_workspace


@dataclass
class MountedDesk:
    """Owned test factory and exact authenticated request material."""

    app: Flask
    client: FlaskClient
    headers: dict[str, str]
    calls: list[str]
    transport: Any


def _configuration() -> dict[str, Any]:
    """Select an existing labelled portable request, not fabricated evidence."""
    corpus = json.loads((Path(__file__).parent / "fixtures/native-autonomy-v2.json").read_text())
    request = next(case["value"] for case in corpus["cases"] if case["id"] == "ConfigureRequestV2-positive")
    request["config"].update(run_id="mounted-native", broker="dhan", account_id="Mounted", environment="production")
    return request


@pytest.fixture
def mounted_desk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory: Callable[[], Any],
    owned_flask_apps: Any,
    request: pytest.FixtureRequest | None,
) -> Iterator[MountedDesk]:
    """Use the normal factory with genuine disposable account custody.

    Explicit CONNECT uses the normal account owner and installed SDK with inert
    profile/trade HTTP. No real account, master read, model or financial I/O is
    permitted; no pre-populated registry is adopted by the factory.
    """
    from datetime import datetime, timedelta
    from uuid import uuid4
    from zoneinfo import ZoneInfo

    import requests

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.secure_file import harden_directory

    harden_directory(tmp_path)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)

    def configure(value: dict[str, Any]) -> None:
        """Install test-owned ACLs before the normal factory acquires account storage."""
        value["brokers"]["account_acls"] = {
            "dhan": {"Mounted": ["mounted-operator", "bounded:mounted-native"]},
        }
        if getattr(request, "param", None) == "kotak_acl":
            value["brokers"]["account_acls"]["kotakneo"] = {
                "KotakMounted": ["mounted-operator", "bounded:mounted-native"],
            }

    compare_and_swap_workspace(tmp_path, None, configure)
    calls: list[str] = []
    expiry = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)

    class Transport:
        """Only external HTTP is inert; login, SDK and adapter remain real."""

        def __init__(self) -> None:
            self.before_read: Callable[[], None] = lambda: None
            self.authentication_calls: list[str] = []

        def send(self, request: requests.PreparedRequest) -> requests.Response:
            """Supply separately labelled profile and daily-trade observations."""
            assert request.method == "GET"
            if request.url == "https://api.dhan.co/v2/profile":
                self.authentication_calls.append(request.url)
                data: Any = {"dhanClientId": "Mounted", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
            else:
                assert request.url == "https://api.dhan.co/v2/trades/"
                calls.append("trades")
                self.before_read()
                data = []
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(data).encode()
            return response

    transport = Transport()

    def send(_session: requests.Session, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        return transport.send(request)

    monkeypatch.setattr(requests.Session, "send", send)
    app = create_flask_app(backend_lease_proof=backend_lease_factory())
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].setup_account("mounted-operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = _create_token("mounted-operator", mode="live", live_mode_unlocked=True)
    client = app.test_client()
    headers = {"Authorization": "Bearer " + token}
    try:
        connected = client.post("/api/v1/native/accounts", json={
            "adapter_id": "dhan", "account_id": "Mounted",
            "credentials": {"client_id": "Mounted", "access_token": "synthetic-access"},
        }, headers={**headers, "Idempotency-Key": str(uuid4())})
        assert connected.status_code == 200, connected.get_json()
        assert connected.get_json()["receipt"]["state"] == "committed"
        assert transport.authentication_calls == ["https://api.dhan.co/v2/profile"]
        assert calls == []
        yield MountedDesk(app, client, headers, calls, transport)
    finally:
        owned_flask_apps.close()


@pytest.mark.integration
def test_normal_factory_mounts_versioned_configuration_without_authority(mounted_desk: MountedDesk) -> None:
    """A real mounted configuration is durable, local and explicitly unarmed."""
    desk = mounted_desk
    response = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert response.status_code == 201, response.get_json()
    view = response.get_json()["data"]
    from flinttrade_core.native_autonomy_contracts_v2 import RunViewV2

    parsed = RunViewV2.model_validate(view)
    assert parsed.scope.account_id == "Mounted"
    assert parsed.scope.actor == "bounded:mounted-native"
    assert parsed.effective_authority == "none"
    assert parsed.entry_state == "ungranted" and parsed.producer_state == "not_started"
    assert parsed.grant is None and parsed.report is None
    assert desk.calls == []
    status = desk.client.get("/api/v1/execution-sessions/mounted-native/autonomy-v2", headers=desk.headers)
    assert status.status_code == 200, status.get_json()
    assert status.get_json()["data"] == view
    assert desk.calls == []
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.integration
def test_explicit_inspection_persists_real_canonical_reads_without_qualifying(mounted_desk: MountedDesk) -> None:
    """A bounded daily capture is useful evidence, never complete lifetime proof."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201, created.get_json()
    scope = created.get_json()["data"]["scope"]
    request = {
        "schema_version": "2", "run_id": scope["run_id"],
        "expected_binding_revision": scope["binding_revision"],
        "read_plan": {"surfaces": ["trades"], "max_reads": 1, "max_pages": 1,
                      "deadline_ms": int(time.time() * 1000) + 10000},
    }
    response = desk.client.post("/api/v1/execution-sessions/mounted-native/autonomy-v2/inspect",
                               json=request, headers=desk.headers)
    assert response.status_code == 200, response.get_json()
    view = response.get_json()["data"]
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.native_autonomy_contracts_v2 import RunViewV2

    parsed = RunViewV2.model_validate(view)
    assert parsed.report is not None and parsed.report.status == "blocked"
    assert parsed.report.dimensions.observations.evidence_ref is not None
    assert parsed.report.dimensions.observations.status != "verified"
    assert parsed.report.dimensions.fees.status == "missing"
    assert parsed.effective_authority == "none" and parsed.grant is None
    assert desk.calls == ["trades"]
    observation = desk.app.config["ORDER_LIFECYCLE_LEDGER"].observation_snapshot(BrokerSelector("dhan", "Mounted"))
    assert observation.generation > 0 and not observation.admission_available
    assert "lifetime_coverage_unavailable" in observation.missing_evidence
    status = desk.client.get("/api/v1/execution-sessions/mounted-native/autonomy-v2", headers=desk.headers)
    assert status.status_code == 200
    assert status.get_json()["data"]["report"] == view["report"]
    assert desk.calls == ["trades"]


@pytest.mark.integration
def test_empty_qualification_evaluates_owners_without_provider_reads(mounted_desk: MountedDesk) -> None:
    """A qualification request selects no client proof and cannot fetch implicitly."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    url = "/api/v1/execution-sessions/mounted-native/autonomy-v2/qualify"
    refused = desk.client.post(url, json={"verified": True}, headers=desk.headers)
    assert refused.status_code == 409, refused.get_json()
    result = desk.client.post(url, json={}, headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    view = result.get_json()["data"]
    assert view["report"]["status"] == "blocked" and view["grant"] is None
    assert view["report"]["dimensions"]["software"]["status"] == "verified"
    assert view["report"]["dimensions"]["account_eligibility"]["status"] == "missing"
    assert view["report"]["dimensions"]["fees"]["status"] == "missing"
    assert desk.calls == []


@pytest.mark.integration
def test_options_configuration_uses_its_nominal_view(mounted_desk: MountedDesk) -> None:
    """Options remain a distinct policy while shared actions keep schema two."""
    from flinttrade_core.native_autonomy_contracts_v2 import OptionsRunViewV2, RunViewV2
    from pydantic import ValidationError

    corpus = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())
    request = next(case["value"] for case in corpus["cases"] if case["id"] == "options-ConfigureRequestV2-positive")
    request["config"].update(run_id="mounted-native", broker="dhan", account_id="Mounted", environment="production")
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=request, headers=desk.headers)
    assert created.status_code == 201, created.get_json()
    view = created.get_json()["data"]
    assert OptionsRunViewV2.model_validate(view).config.risk.profile_version == "index_options_v1"
    with pytest.raises(ValidationError):
        RunViewV2.model_validate(view)
    response = desk.client.post("/api/v1/execution-sessions/mounted-native/autonomy-v2/qualify",
                                json={}, headers=desk.headers)
    assert response.status_code == 200, response.get_json()
    parsed = OptionsRunViewV2.model_validate(response.get_json()["data"])
    assert parsed.report is not None and parsed.report.schema_version == "2"
    assert parsed.effective_authority == "none" and parsed.grant is None
    assert desk.calls == []


@pytest.mark.integration
def test_freshness_is_local_and_stale_account_does_not_block_stop(mounted_desk: MountedDesk) -> None:
    """Retired account evidence becomes stale without a hidden broker refresh."""
    from flinttrade_core.broker_identity import BrokerSelector

    desk = mounted_desk
    config = _configuration()
    config["config"]["risk"]["max_mark_age_ms"] = 60000
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=config, headers=desk.headers)
    assert created.status_code == 201
    scope = created.get_json()["data"]["scope"]
    url = "/api/v1/execution-sessions/mounted-native"
    inspected = desk.client.post(url + "/autonomy-v2/inspect", json={
        "schema_version": "2", "run_id": "mounted-native", "expected_binding_revision": scope["binding_revision"],
        "read_plan": {"surfaces": ["trades"], "max_reads": 1, "max_pages": 1,
                      "deadline_ms": int(time.time() * 1000) + 10000},
    }, headers=desk.headers)
    assert inspected.status_code == 200, inspected.get_json()
    assert inspected.get_json()["data"]["observation_freshness"] == "fresh"
    selector = BrokerSelector("dhan", "Mounted")
    registry = desk.app.config["REGISTRY"]
    desk.app.extensions["flinttrade.registry_publication_owner"].remove_session_for_exact(
        selector, expected_registry=registry.snapshot_selector(selector),
    )
    stale = desk.client.get(url + "/autonomy-v2", headers=desk.headers)
    assert stale.status_code == 200
    assert stale.get_json()["data"]["observation_freshness"] == "stale"
    generation = desk.client.get(url, headers=desk.headers).get_json()["data"]["generation"]
    stopped = desk.client.post(url + "/stop", json={
        "account": "dhan:Mounted", "environment": "live", "expected_generation": generation,
    }, headers=desk.headers)
    assert stopped.status_code == 200
    assert desk.calls == ["trades"]


@pytest.mark.integration
def test_held_inspection_does_not_block_stop_or_publish_a_stale_report(mounted_desk: MountedDesk) -> None:
    """Real SDK waits occur outside the execution lock, followed by revision CAS."""
    import threading

    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    scope = created.get_json()["data"]["scope"]
    url = "/api/v1/execution-sessions/mounted-native"
    generation = desk.client.get(url, headers=desk.headers).get_json()["data"]["generation"]
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    outcomes: dict[str, Any] = {}

    def hold() -> None:
        entered.set()
        assert release.wait(10)

    def inspect() -> None:
        with desk.app.test_client() as client:
            outcomes["inspect"] = client.post(url + "/autonomy-v2/inspect", json={
                "schema_version": "2", "run_id": "mounted-native",
                "expected_binding_revision": scope["binding_revision"],
                "read_plan": {"surfaces": ["trades"], "max_reads": 1, "max_pages": 1,
                              "deadline_ms": int(time.time() * 1000) + 15000},
            }, headers=desk.headers)

    def stop() -> None:
        with desk.app.test_client() as client:
            outcomes["stop"] = client.post(url + "/stop", json={
                "account": "dhan:Mounted", "environment": "live", "expected_generation": generation,
            }, headers=desk.headers)
        stopped.set()

    desk.transport.before_read = hold
    reader = threading.Thread(target=inspect)
    stopper = threading.Thread(target=stop)
    try:
        reader.start()
        assert entered.wait(5)
        stopper.start()
        assert stopped.wait(2), "Stop blocked behind broker I/O"
        assert not release.is_set()
        assert outcomes["stop"].status_code == 200
        release.set()
        reader.join(5)
        assert not reader.is_alive()
        assert outcomes["inspect"].status_code == 409, outcomes["inspect"].get_json()
        view = desk.client.get(url + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert view["entry_state"] == "retired" and view["report"] is None
    finally:
        release.set()
        reader.join(10)
        if stopper.ident is not None:
            stopper.join(10)
        assert not reader.is_alive() and not stopper.is_alive()


@pytest.mark.integration
@pytest.mark.parametrize("target", ["operator", "account", "bounded_actor"])
def test_configuration_refuses_unowned_canonical_scope(mounted_desk: MountedDesk, target: str) -> None:
    """Both authenticated human and immutable bounded actor require real ACLs."""
    desk = mounted_desk
    body = _configuration()
    headers = desk.headers
    if target == "operator":
        with desk.app.app_context():
            token = _create_token("another-operator", mode="live", live_mode_unlocked=True)
        headers = {"Authorization": "Bearer " + token}
    elif target == "account":
        body["config"]["account_id"] = "mounted"
    else:
        body["config"]["run_id"] = "another-run"
    response = desk.client.post("/api/v1/execution-sessions/native-v2", json=body, headers=headers)
    assert response.status_code == 409, response.get_json()
    assert desk.calls == []
    assert desk.app.config["EXECUTION_SESSIONS"].list(
        desk.app.config["EXECUTION_SESSIONS"].autonomy._operator(headers["Authorization"][7:])[0].actor_ref,
    ) == []


@pytest.mark.integration
def test_kill_is_reported_without_inventing_post_stop_authority(mounted_desk: MountedDesk) -> None:
    """The real L5 latch remains visible in the versioned read projection."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    desk.app.config["SAFETY"].l5_kill.activate("synthetic native-v2 control")
    response = desk.client.get("/api/v1/execution-sessions/mounted-native/autonomy-v2", headers=desk.headers)
    assert response.status_code == 200, response.get_json()
    view = response.get_json()["data"]
    assert view["global_kill"] is True
    assert view["entry_state"] == "retired" and view["effective_authority"] == "none"
    assert desk.calls == []


def _crash_configured_native(path: Path) -> None:
    """Leave a real committed configuration by exiting before normal cleanup."""
    import os

    from tests.flask_app_lifecycle import owned_flask_apps as factory_fixture

    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret = path / "master_password"
    secret.write_text("pytest-master-password")
    secret.chmod(0o600)
    patcher = pytest.MonkeyPatch()
    patcher.setenv("FLINTTRADE_WORKSPACE_DIR", str(path))
    factory_custody = factory_fixture.__wrapped__(patcher)
    apps = next(factory_custody)
    lease = acquire_backend_instance_lease()
    session = mounted_desk.__wrapped__(path, patcher, lambda: lease.proof, apps, None)
    try:
        desk = next(session)
        response = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
        assert response.status_code == 201, response.get_json()
        os._exit(0)
    finally:
        session.close()
        factory_custody.close()
        lease.release()


@pytest.mark.integration
def test_normal_factory_retires_crash_image_before_any_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_lease_factory: Callable[[], Any], owned_flask_apps: Any,
) -> None:
    """Actual child loss, lease reacquisition and factory recovery require no GET."""
    import os
    import sqlite3
    import subprocess
    import sys

    import requests

    from flinttrade_core.app import create_flask_app

    root = tmp_path / "crash-workspace"
    code = (
        "import os; from pathlib import Path; "
        f"os.environ['FLINTTRADE_WORKSPACE_DIR']={str(root)!r}; "
        "from packages.core.core.tests.test_native_workflow_v2 import _crash_configured_native; "
        f"_crash_configured_native(Path({str(root)!r}))"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True,
                            timeout=60, env=dict(os.environ))
    assert result.returncode == 0, result.stdout + result.stderr
    database_path = root / "execution-sessions/autonomy.sqlite"
    with sqlite3.connect(database_path) as database:
        prior = json.loads(database.execute("SELECT data FROM runs WHERE run_id='mounted-native'").fetchone()[0])
    assert prior["entry_state"] == "ungranted"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(root))
    calls: list[str] = []

    def forbidden(_session: requests.Session, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        calls.append(str(request.url))
        pytest.fail("startup cannot perform provider I/O")

    monkeypatch.setattr(requests.Session, "send", forbidden)
    app = create_flask_app(backend_lease_proof=backend_lease_factory())
    try:
        with sqlite3.connect(database_path) as database:
            recovered = json.loads(database.execute(
                "SELECT data FROM runs WHERE run_id='mounted-native'").fetchone()[0])
        assert recovered["entry_state"] == "retired"
        assert recovered["config_v2"] == prior["config_v2"]
        assert recovered["scope_v2"] == prior["scope_v2"]
        assert app.config["EXECUTION_SESSIONS"].owners == {}
        assert calls == []
    finally:
        owned_flask_apps.close()


@pytest.mark.integration
def test_unknown_persisted_version_refuses_without_rewriting_rows(mounted_desk: MountedDesk) -> None:
    """A future/partial record is retained, not silently migrated or reset."""
    from flinttrade_core.execution_sessions import ExecutionSessions

    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    owner = desk.app.config["EXECUTION_SESSIONS"]
    with owner.autonomy.db.transaction() as database:
        raw = database.execute("SELECT data FROM runs WHERE run_id='mounted-native'").fetchone()[0]
        changed = json.loads(raw)
        changed["schema_version"] = "future-unsupported"
        encoded = json.dumps(changed, sort_keys=True)
        database.execute("UPDATE runs SET data=? WHERE run_id='mounted-native'", (encoded,))
    owner.close()
    successor = ExecutionSessions(desk.app, owner.path)
    desk.app.config["EXECUTION_SESSIONS"] = successor
    import sqlite3

    try:
        with pytest.raises(ValueError):
            _ = successor.autonomy
        with sqlite3.connect(owner.path / "autonomy.sqlite") as database:
            after = database.execute("SELECT data FROM runs WHERE run_id='mounted-native'").fetchone()[0]
        assert after == encoded
        assert desk.calls == []
    finally:
        # Restore only fixture-owned fault data after measurement so ordinary
        # cleanup can drain. This rescue is not a product recovery result.
        with sqlite3.connect(owner.path / "autonomy.sqlite") as database:
            database.execute("UPDATE runs SET data=? WHERE run_id='mounted-native'", (raw,))


@pytest.mark.integration
def test_versioned_get_without_custody_never_initialises_native_storage(mounted_desk: MountedDesk) -> None:
    """An absent run inspection does not create an authority database."""
    desk = mounted_desk
    owner = desk.app.config["EXECUTION_SESSIONS"]
    assert not (owner.path / "autonomy.sqlite").exists()
    response = desk.client.get("/api/v1/execution-sessions/absent/autonomy-v2", headers=desk.headers)
    assert response.status_code == 409
    assert not (owner.path / "autonomy.sqlite").exists()
    assert desk.calls == []


@pytest.mark.integration
def test_v2_restart_retires_entries_without_rewriting_configuration(mounted_desk: MountedDesk) -> None:
    """Recovery uses the existing custody path and cannot re-arm a saved run."""
    from flinttrade_core.execution_sessions import ExecutionSessions

    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    before = created.get_json()["data"]
    owner = desk.app.config["EXECUTION_SESSIONS"]
    owner.close()
    desk.app.config["EXECUTION_SESSIONS"] = ExecutionSessions(desk.app, owner.path)
    result = desk.client.get("/api/v1/execution-sessions/mounted-native/autonomy-v2", headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    view = result.get_json()["data"]
    assert view["config"] == before["config"] and view["scope"] == before["scope"]
    assert view["entry_state"] == "retired" and view["effective_authority"] == "none"
    assert view["producer_state"] == "not_started"
    assert desk.calls == []


@pytest.mark.integration
def test_shared_stop_retires_v2_and_legacy_inspection_cannot_misclassify_it(mounted_desk: MountedDesk) -> None:
    """The original generation-bound Stop reaches the same durable v2 owner."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    url = "/api/v1/execution-sessions/mounted-native"
    legacy = desk.client.get(url + "/autonomy", headers=desk.headers)
    assert legacy.status_code == 409, legacy.get_json()
    shared = desk.client.get(url, headers=desk.headers).get_json()["data"]
    assert shared["autonomy_v2"]["schema_version"] == "2"
    result = desk.client.post(url + "/stop", json={
        "account": "dhan:Mounted", "environment": "live", "expected_generation": shared["generation"],
    }, headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    view = desk.client.get(url + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    assert view["entry_state"] == "retired" and view["effective_authority"] == "none"
    assert desk.calls == []


@pytest.mark.integration
@pytest.mark.parametrize("environment", ["synthetic", "demo_broker"])
def test_requested_environment_never_relabels_production_credentials(
    mounted_desk: MountedDesk, environment: str,
) -> None:
    """Untrusted environment labels cannot select an inert-guard shortcut."""
    config = _configuration()
    config["config"]["environment"] = environment
    response = mounted_desk.client.post("/api/v1/execution-sessions/native-v2", json=config,
                                        headers=mounted_desk.headers)
    assert response.status_code == 409
    assert mounted_desk.calls == []


@pytest.mark.integration
@pytest.mark.parametrize("change", ["deadline", "reads", "pages", "surface", "run", "binding", "proof"])
def test_invalid_inspection_plan_never_calls_provider(mounted_desk: MountedDesk, change: str) -> None:
    """Bad bounds or forged selections refuse before the canonical read port."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201
    scope = created.get_json()["data"]["scope"]
    body: dict[str, Any] = {
        "schema_version": "2", "run_id": scope["run_id"],
        "expected_binding_revision": scope["binding_revision"],
        "read_plan": {"surfaces": ["trades"], "max_reads": 1, "max_pages": 1,
                      "deadline_ms": int(time.time() * 1000) + 10000},
    }
    if change == "deadline":
        body["read_plan"]["deadline_ms"] = 1
    elif change == "reads":
        body["read_plan"]["max_reads"] = 0
    elif change == "pages":
        body["read_plan"]["max_pages"] = False
    elif change == "surface":
        body["read_plan"]["surfaces"] = ["unsupported"]
    elif change == "run":
        body["run_id"] = "other-run"
    elif change == "binding":
        body["expected_binding_revision"] = "b" * 64
    else:
        body["verified"] = True
    result = desk.client.post("/api/v1/execution-sessions/mounted-native/autonomy-v2/inspect",
                              json=body, headers=desk.headers)
    assert result.status_code == 409, result.get_json()
    assert desk.calls == []
