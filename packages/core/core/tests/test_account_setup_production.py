"""Normal account composition with real SDKs and inert HTTP transport.

These are synthetic account fixtures, not broker or options qualification.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import requests

from flinttrade_core import auth_routes
from flinttrade_core.app import create_flask_app
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.workspace_migrations import read_workspace_snapshot


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from flask import Flask
    from flinttrade_core.backend_instance import BackendLeaseProof
    from pathlib import Path
    from tests.flask_app_lifecycle import FactoryApps
    from werkzeug.test import TestResponse

pytestmark = pytest.mark.integration
_PROFILE_EXPIRY = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).replace(second=0, microsecond=0)
_PROFILE_VALIDITY = _PROFILE_EXPIRY.strftime("%d/%m/%Y %H:%M")


@pytest.fixture
def production_app(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
    request: "pytest.FixtureRequest",
) -> "Iterator[tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]]":
    """Own the normal SDK-backed account factory with only its HTTP transport replaced.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
        request: Fixture request carrying the optional composition parameter.

    Yields:
        App, operator token, workspace and inert transport call ledger until factory cleanup.

    Raises:
        TimeoutError: The existing factory cleanup owner cannot drain within its bound.
    """
    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    if getattr(request, "param", None) == "with_acl":
        from flinttrade_core.workspace_migrations import default_workspace_config, write_workspace_config

        config = default_workspace_config()
        config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["operator"]}}
        write_workspace_config(tmp_path, config, expected_version=None)
    calls = []

    def send(session, request, **kwargs):
        calls.append((session, request.method, request.url))
        lifecycle = app.extensions["flinttrade.account_setup"].lifecycle
        if lifecycle.snapshot().active:
            app.config["TEST_AUTH_CUSTODY"].append(lifecycle.snapshot().cleanup_pending)
        assert request.method == "GET"
        assert request.url in {"https://api.dhan.co/v2/fundlimit", "https://api.dhan.co/v2/profile"}
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {
                "dhanClientId": "Synthetic",
                "availabelBalance": 1000.0,
                "sodLimit": 1000.0,
                "utilizedAmount": 0.0,
                **({"tokenValidity": _PROFILE_VALIDITY} if request.url.endswith("/profile") else {}),
            }
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    factory_options = {}
    if getattr(request, "param", None) == "with_resolvers":
        factory_options["native_reference_resolvers"] = _synthetic_resolvers()
    app = create_flask_app(backend_lease_proof=backend_lease_factory(), **factory_options)
    app.config["TEST_AUTH_CUSTODY"] = []
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = auth_routes._create_token("operator", mode="explore")
    yield app, token, tmp_path, calls
    owned_flask_apps.close()


def connect(app: "Flask", token: "str", *, key: "str | None" = None, account: "str" = "Synthetic") -> "TestResponse":
    """Send an explicit synthetic Dhan CONNECT through the normal account route.

    Args:
        app: App retaining the execution-session and account lifecycle owners.
        token: Synthetic operator session token used by the HTTP request.
        key: Explicit idempotency key, or None to generate one for this request.
        account: Exact synthetic account label sent to account setup.

    Returns:
        Actual HTTP test response, including any refused or unknown disposition.
    """
    return app.test_client().post(
        "/api/v1/native/accounts",
        json={
            "adapter_id": "dhan",
            "account_id": account,
            "credentials": {"client_id": "Synthetic", "access_token": "synthetic-access"},
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid4())},
    )


def test_default_factory_connect_uses_real_dhan_sdk_only_on_explicit_action(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Invoke the installed SDK only for explicit CONNECT, not catalogue reads or replay.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    client = app.test_client()
    assert calls == []
    assert client.get("/api/v1/native/brokers", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert calls == []
    key = str(uuid4())
    result = connect(app, token, key=key)
    assert result.status_code == 200, result.json
    assert result.json["receipt"]["state"] == "committed"
    assert result.json["runtimeStatus"] == "session_present"
    assert app.config["TEST_AUTH_CUSTODY"] == [1]
    setup = app.extensions["flinttrade.account_setup"]
    assert app.extensions["flinttrade_broker_dependencies"].read_owner is setup.runtime.read_owner
    selector = BrokerSelector("dhan", "Synthetic")
    record = setup.registry.snapshot_exact_state(selector)
    assert record.binding is not None
    assert setup.store.operation(UUID(key)).witness == setup.store.head()
    assert len(calls) == 1
    assert calls[0][1:] == ("GET", "https://api.dhan.co/v2/profile")
    assert b"synthetic-access" not in (path / "credentials.db").read_bytes()
    brokers = read_workspace_snapshot(path).as_dict()["brokers"]
    assert brokers["account_acls"] == {}
    assert brokers["execution"]["default"] == ""
    assert app.config["BROKER_ROUTER"] is None
    replay = connect(app, token, key=key)
    assert replay.json == result.json
    assert len(calls) == 1


def test_applied_expired_lifetime_is_not_ready_on_durable_replay(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """An applied owner observation never substitutes for current session lookup.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable

    app, token, path, calls = production_app
    key = str(uuid4())
    first = connect(app, token, key=key)
    assert first.json["runtimeStatus"] == "session_present"
    setup = app.extensions["flinttrade.account_setup"]
    selector = BrokerSelector("dhan", "Synthetic")
    authority = setup.runtime._provider.current_authority_for(selector)
    handle = setup.registry.get_connected_session_for(selector, current_authority=authority)
    generation = handle.version.registry_version.generation
    # Exercise the actual publication owner. This is not a substitute for the
    # separately qualified adapter's sealed liveness observation protocol.
    setup.registry_owner.shorten_session_expiry(handle, 0.0, current_authority=authority)
    state = setup.registry.snapshot_exact_state(selector)
    assert state.expires_at == 0.0
    assert state.registry_version.generation == generation + 1
    with pytest.raises(RegistrySessionUnavailable):
        setup.registry.get_connected_session_for(selector, current_authority=authority)
    replay = connect(app, token, key=key)
    assert replay.status_code == 200
    assert replay.json["receipt"] == first.json["receipt"]
    assert replay.json["runtimeStatus"] == "session_unavailable"
    assert len(calls) == 1  # Durable replay does not authenticate or fetch a profile.
    assert setup.lifecycle.close_and_drain(2)
    assert setup.lifecycle.snapshot().cleanup_pending == 0
    assert setup.registry.snapshot_exact_state(selector).binding is None


def test_shortened_live_lifetime_retains_same_owner_cleanup(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """A still-live shortened generation remains disposable by its original owner.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["runtimeStatus"] == "session_present"
    setup = app.extensions["flinttrade.account_setup"]
    selector = BrokerSelector("dhan", "Synthetic")
    authority = setup.runtime._provider.current_authority_for(selector)
    handle = setup.registry.get_connected_session_for(selector, current_authority=authority)
    setup.registry_owner.shorten_session_expiry(handle, handle.expires_at - 60, current_authority=authority)
    current = setup.registry.get_connected_session_for(selector, current_authority=authority)
    assert current.version.credential_version == authority.credential_version
    assert setup.lifecycle.close_and_drain(2)
    assert setup.lifecycle.snapshot().cleanup_pending == 0
    assert setup.registry.snapshot_exact_state(selector).binding is None
    assert len(calls) == 1


def test_caller_label_cannot_rebind_the_authenticated_account(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Reject a foreign caller label without rebinding the authenticated account.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    before = read_workspace_snapshot(path)
    response = connect(app, token, account="Foreign")
    assert response.status_code == 400, response.json
    assert calls == []
    assert read_workspace_snapshot(path) == before
    assert not app.config["CREDENTIAL_STORE"].selector_state(BrokerSelector("dhan", "Foreign")).present


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_default_factory_kotak_authentication_uses_installed_sdk(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
    owned_flask_apps: "FactoryApps",
    cleanup_failure: "bool",
) -> None:
    """Preserve real Kotak SDK authentication and retained local transport cleanup.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
        cleanup_failure: Whether the first local transport close fails and requires same-owner retry.
    """
    import httpx
    from neo_api_client.utils.neo_utility import CONFIG_SERVICE_URL_PROD

    app, token, path, dhan_calls = production_app
    calls = []

    def send(client, request, **kwargs):
        calls.append((client, request.method, str(request.url)))
        if request.url.path.endswith("tradeApiLogin"):
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "mobileNumber": "+910000000000",
                "ucc": "Synthetic",
                "totp": "000000",
            }
            data = {
                "token": "synthetic-view",
                "sid": "synthetic-sid",
                "ucc": "Synthetic",
                "kType": "View",
                "status": "success",
            }
        elif request.url.path.endswith("tradeApiValidate"):
            assert request.method == "POST" and json.loads(request.content) == {"mpin": "000000"}
            data = {
                "token": "synthetic-trade",
                "sid": "synthetic-sid",
                "ucc": "Synthetic",
                "kType": "Trade",
                "status": "success",
                "baseUrl": "https://example.invalid",
                "dataCenter": "synthetic",
            }
        elif str(request.url).split("?", 1)[0] == CONFIG_SERVICE_URL_PROD:
            assert request.method == "GET"
            data = {"configs": {}}
        else:
            assert request.method == "GET" and request.url.path.endswith("get-client-ip")
            return httpx.Response(
                200, request=request, json={"status": "success", "stCode": 1000, "data": [{"ip": "192.0.2.1"}]}
            )
        return httpx.Response(200, request=request, json={"data": data})

    monkeypatch.setattr(httpx.Client, "send", send)
    response = app.test_client().post(
        "/api/v1/native/accounts",
        json={
            "adapter_id": "kotakneo",
            "account_id": "Synthetic",
            "credentials": {
                "consumer_key": "synthetic-key",
                "mobile_number": "+910000000000",
                "ucc": "Synthetic",
                "totp": "000000",
                "mpin": "000000",
            },
        },
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "committed", response.json
    assert len(calls) == 4
    assert dhan_calls == []
    vault = app.config["CREDENTIAL_STORE"]
    assert "totp" not in vault.retrieve_for("kotakneo", "Synthetic")
    record = app.config["REGISTRY"].snapshot_exact_state(BrokerSelector("kotakneo", "Synthetic"))
    assert record.read_only is True
    assert app.config["BROKER_ROUTER"] is None
    transport = calls[0][0]._transport
    original_close = transport.close
    attempts = []
    if cleanup_failure:
        from flinttrade_core.app import _shutdown_rotation_scheduler

        def fail_once():
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError("synthetic local pool close failure")
            original_close()

        monkeypatch.setattr(transport, "close", fail_once)
        with pytest.raises(TimeoutError, match="broker account lifecycle did not drain"):
            _shutdown_rotation_scheduler(app, timeout=0.02)
        assert app.extensions["flinttrade.account_setup"].lifecycle.snapshot().cleanup_pending == 1
    try:
        owned_flask_apps.close()
        assert all(client.is_closed for client, _, _ in calls)
        assert len(calls) == 4  # no SDK logout or other provider call during disposal
        if cleanup_failure:
            assert len(attempts) == 2, "a closed client flag is not a completed transport disposal"
    finally:
        original_close()  # rescue only after the passive disposal observation


def test_restart_requires_explicit_reconnect_and_preserves_vault_identity(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Reopen provider-free and require explicit reconnect while retaining vault incarnation.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    original = app.extensions["flinttrade.account_setup"]
    before = original.credentials.selector_state(BrokerSelector("dhan", "Synthetic"))
    snapshot = read_workspace_snapshot(path)
    proof = original.proof
    owned_flask_apps.close()
    restarted = create_flask_app(backend_lease_proof=proof)
    setup = restarted.extensions["flinttrade.account_setup"]
    assert len(calls) == 1  # reopening is provider-free
    assert setup.credentials.selector_state(BrokerSelector("dhan", "Synthetic")) == before
    assert read_workspace_snapshot(path) == snapshot
    assert setup.registry.snapshot_exact_state(BrokerSelector("dhan", "Synthetic")) is None
    response = restarted.test_client().post(
        "/api/v1/native/accounts/dhan/Synthetic/login",
        json={},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "committed", response.json
    assert response.json["receipt"]["kind"] == "reconnect"
    assert response.json["runtimeStatus"] == "session_present"
    assert len(calls) == 2
    after = setup.credentials.selector_state(BrokerSelector("dhan", "Synthetic"))
    assert after.version.vault_incarnation == before.version.vault_incarnation
    assert after.version.generation == before.version.generation + 1


def _restart_child(root, phase, key):
    """Real process-loss diagnostic; never force-release a durable claim."""
    import os
    import threading
    from pathlib import Path
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    path = Path(root)
    path.mkdir(mode=0o700, exist_ok=True)
    if phase.startswith("crash-"):
        (path / "master_password").write_text("synthetic-password")
        (path / "master_password").chmod(0o600)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(path)
    calls = []
    release_probe = threading.Event()

    def send(session, request, **kwargs):
        calls.append(request.url)
        assert request.method == "GET" and request.url == "https://api.dhan.co/v2/profile"
        if phase == "crash-unknown":
            raise requests.Timeout("synthetic held outcome")
        if phase == "crash-held-probe":
            assert release_probe.wait(38)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {
                "dhanClientId": "Synthetic",
                "tokenValidity": _PROFILE_VALIDITY,
                "availabelBalance": 1000,
                "sodLimit": 1000,
                "utilizedAmount": 0,
            }
        ).encode()
        return response

    requests.Session.send = send
    lease = acquire_backend_instance_lease()
    app = create_flask_app(backend_lease_proof=lease.proof)
    setup = app.extensions["flinttrade.account_setup"]
    if phase.startswith("crash-"):
        app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
        with app.app_context():
            token = auth_routes._create_token("operator", mode="explore")
        export_custody = []
        if phase == "crash-export":
            adapter = setup.drivers["dhan"].adapter
            export = adapter.replay_credentials

            def fail_export(credentials, session):
                replay = export(credentials, session)
                export_custody.append(
                    (setup.lifecycle.snapshot().cleanup_pending, replay["access_token"] == session.access_token)
                )
                raise OSError("synthetic replay export interruption")

            adapter.replay_credentials = fail_export
        if phase in {"crash-unknown", "crash-held-probe", "crash-export"}:
            try:
                response = connect(app, token, key=key)
                if phase == "crash-held-probe":
                    assert setup.lifecycle.snapshot().cleanup_pending == 1
                    assert not setup.lifecycle.close_and_drain(0)
            finally:
                release_probe.set()
            assert response.json["receipt"]["state"] == "authentication_unknown", response.json
            if phase == "crash-export":
                assert export_custody == [(1, True)]
            if phase == "crash-unknown":
                assert connect(app, token, key=key).json == response.json
            assert len(calls) == 1
            assert not setup.lifecycle.close_and_drain(2)
            assert setup.lifecycle.snapshot().cleanup_pending == 0
            assert setup.store.active_operation(setup.store.owner_capability(lease.proof)) is not None
            print("UNKNOWN_DISPOSED_NOT_SETTLED", flush=True)
            os._exit(72)
        setup.store.apply = lambda *args: os._exit(72)
        connect(app, token, key=key)
        raise AssertionError("actual post-witness fault was not reached")
    if phase == "recover-unknown":
        assert calls == []
        assert setup.store.operation(UUID(key)).receipt.state.value == "authentication_unknown"
        assert setup.lifecycle.snapshot().active
        assert not setup.lifecycle.close_and_drain(0.1)
        assert setup.store.active_operation(setup.store.owner_capability(lease.proof)).operation_id == UUID(key)
        assert not setup.credentials.selector_state(BrokerSelector("dhan", "Synthetic")).present
        assert calls == []
        print("UNKNOWN_RECOVERY_RETAINS_CLAIM", flush=True)
        os._exit(0)
    assert phase == "recover-after-witness"
    assert calls == []
    operation = setup.store.operation(UUID(key))
    assert operation.receipt.state.value == "committed"
    assert setup.workspace.assert_coherent().as_dict()["_broker_account_store"] == operation.witness.to_dict()
    assert setup.store.active_operation(setup.store.owner_capability(lease.proof)) is None
    assert setup.registry.snapshot_exact_state(BrokerSelector("dhan", "Synthetic")) is None
    assert setup.runtime.read_owner is None
    print("PROVIDER_FREE_COMMITTED_RECOVERY_WITHOUT_SESSION", flush=True)
    os._exit(0)


@pytest.mark.parametrize(
    "crash,recover,message",
    [
        ("crash-after-witness", "recover-after-witness", "PROVIDER_FREE_COMMITTED_RECOVERY_WITHOUT_SESSION"),
        ("crash-unknown", "recover-unknown", "UNKNOWN_RECOVERY_RETAINS_CLAIM"),
        ("crash-held-probe", "recover-unknown", "UNKNOWN_RECOVERY_RETAINS_CLAIM"),
    ],
)
def test_restart_recovers_actual_workspace_commit_before_vault_ack(
    tmp_path: "Path",
    crash: "str",
    recover: "str",
    message: "str",
) -> None:
    """Recover the real interrupted transaction without inventing a live session.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        crash: Child phase that exits with the retained account transaction unfinished.
        recover: Successor child phase used to inspect durable recovery.
        message: Exact child success marker required by the parent assertion.
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    key = str(uuid4())
    code = (

            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from packages.core.core.tests.test_account_setup_production import _restart_child\n"
            "_restart_child(*sys.argv[2:])\n"

    )

    def run(phase):
        try:
            return subprocess.run(
                [sys.executable, "-B", "-I", "-c", code, str(root), str(tmp_path / "crash-workspace"), phase, key],
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired as error:
            print("Timed-out synthetic child stdout:", error.stdout)
            print("Timed-out synthetic child stderr:", error.stderr)
            raise

    crashed = run(crash)
    assert crashed.returncode == 72, crashed.stdout + crashed.stderr
    recovered = run(recover)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert message in recovered.stdout


def test_actual_dhan_export_failure_retains_custody_and_unknown_across_restart(tmp_path: "Path") -> None:
    """Post-login replay failure disposes locally without settling durable uncertainty.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
    """
    test_restart_recovers_actual_workspace_commit_before_vault_ack(
        tmp_path, "crash-export", "recover-unknown", "UNKNOWN_RECOVERY_RETAINS_CLAIM",
    )


def test_existing_legacy_storage_migrates_without_auth_then_explicitly_adopts(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Preserve legacy ciphertext during migration and adopt credentials only on explicit login.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    import importlib.util
    import sqlite3
    from pathlib import Path
    from flinttrade_core.app import _get_master_password
    from flinttrade_core.workspace_migrations import default_workspace_config, write_workspace_config

    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location(
        "_account_production_credential_fixtures", root / "tests/credential_fixtures.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    selector = BrokerSelector("dhan", "Synthetic")
    salt, cipher = fixtures.legacy_vault(
        tmp_path / "credentials.db",
        _get_master_password(),
        account_id="Synthetic",
        broker="dhan",
        credentials={"client_id": "Synthetic", "access_token": "old-synthetic"},
    )
    config = default_workspace_config()
    config["brokers"]["registered"] = ["dhan:Synthetic"]
    config["brokers"]["account_acls"] = {"dhan": {"Synthetic": ["operator"]}}
    write_workspace_config(tmp_path, config, expected_version=None)
    calls = []

    def send(session, request, **kwargs):
        calls.append(request.url)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(
            {
                "dhanClientId": "Synthetic",
                "tokenValidity": _PROFILE_VALIDITY,
                "availabelBalance": 1000,
                "sodLimit": 1000,
                "utilizedAmount": 0,
            }
        ).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    app = create_flask_app(backend_lease_proof=backend_lease_factory())
    assert calls == []
    setup = app.extensions["flinttrade.account_setup"]
    before = setup.credentials.selector_state(selector)
    assert before.origin == "legacy_pre_workspace_authority"
    with sqlite3.connect(tmp_path / "credentials.db") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT salt,encrypted_creds FROM accounts").fetchone() == (salt, cipher)
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = auth_routes._create_token("operator", mode="explore")
    response = app.test_client().post(
        "/api/v1/native/accounts/dhan/Synthetic/login",
        json={"credentials": {"client_id": "Synthetic", "access_token": "new-synthetic"}},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "committed", response.json
    after = setup.credentials.selector_state(selector)
    assert after.origin == "managed"
    assert after.version.vault_incarnation == before.version.vault_incarnation
    assert after.version.generation == before.version.generation + 1
    assert setup.credentials.retrieve_for("dhan", "Synthetic")["access_token"] == "new-synthetic"
    assert read_workspace_snapshot(tmp_path).as_dict()["brokers"] == config["brokers"]
    assert len(calls) == 1
    read = app.test_client().get(
        "/api/v1/native/accounts/dhan/Synthetic/funds", headers={"Authorization": f"Bearer {token}"}
    )
    assert read.status_code == 200, read.json
    assert read.json["data"]["available_balance"] == 1000.0
    assert read.json["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Synthetic"}
    assert len(calls) == 2
    assert setup.runtime.read_owner is not None


@pytest.mark.parametrize("production_app", ["with_acl"], indirect=True)
@pytest.mark.parametrize(
    "kind,endpoint", [("positions", "positions"), ("holdings", "holdings"), ("orders", "orders"), ("trades", "trades/")]
)
def test_typed_native_books_have_exact_account_and_real_empty_evidence(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
    kind: "str",
    endpoint: "str",
) -> None:
    """Retain exact account provenance and genuine empty SDK books through HTTP.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
        kind: Canonical account book requested through the normal HTTP route.
        endpoint: Native SDK endpoint expected for the selected book.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    reads = []
    endpoints = ["orders", "forever/orders", "super/orders", "alerts/orders"] if kind == "orders" else [endpoint]

    def send(session, request, **kwargs):
        reads.append((request.method, request.url))
        assert request.method == "GET" and request.url == f"https://api.dhan.co/v2/{endpoints[len(reads) - 1]}"
        response = requests.Response()
        response.status_code = 200
        response._content = b"[]"
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    response = app.test_client().get(
        f"/api/v1/native/accounts/dhan/Synthetic/{kind}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.json
    assert response.json["data"] == []
    assert response.json["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Synthetic"}
    assert reads == [("GET", f"https://api.dhan.co/v2/{value}") for value in endpoints]
    assert app.config["BROKER_ROUTER"] is None


def test_normal_factory_keeps_native_read_rate_limits(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Retain capability-derived native read limits in the normal factory.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    from flinttrade_gateway.rate_limiter import BrokerRateLimiter

    app, token, path, calls = production_app
    setup = app.extensions["flinttrade.account_setup"]
    expected = BrokerRateLimiter.from_capabilities(
        {key: value.adapter.capabilities for key, value in setup.drivers.items()}
    ).snapshot()
    observed = app.extensions["flinttrade_broker_dependencies"].rate_limiter.snapshot()
    assert observed == expected
    assert observed["dhan"]["data"] > 0
    assert calls == []


def test_fresh_connect_does_not_grant_reads_without_account_acl(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Keep successful CONNECT distinct from permission to read the account.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    assert connect(app, token).status_code == 200
    before = list(calls)
    response = app.test_client().get(
        "/api/v1/native/accounts/dhan/Synthetic/funds", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403, response.json
    assert calls == before


def test_remove_uses_committed_transaction_without_authentication(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Remove the account once through durable commit and replay without reauthentication.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    setup = app.extensions["flinttrade.account_setup"]
    selector = BrokerSelector("dhan", "Synthetic")
    before = setup.credentials.selector_state(selector)
    key = str(uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
    response = app.test_client().delete("/api/v1/native/accounts/dhan/Synthetic", json={}, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "committed"
    assert response.json["receipt"]["kind"] == "remove"
    assert response.json["runtimeStatus"] == "removed"
    after = setup.credentials.selector_state(selector)
    assert not after.present and after.version.generation == before.version.generation + 1
    assert setup.registry.snapshot_exact_state(selector).binding is None
    assert setup.runtime.read_owner is None
    assert (
        app.test_client().delete("/api/v1/native/accounts/dhan/Synthetic", json={}, headers=headers).json
        == response.json
    )
    assert len(calls) == 1


def test_missing_enrolled_vault_is_not_recreated(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Refuse a missing enrolled vault instead of creating competing empty custody.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    proof = app.config["BACKEND_LEASE_PROOF"]
    owned_flask_apps.close()
    target = path / "credentials.db"
    target.rename(path / "retained-credentials.db")
    with pytest.raises((RuntimeError, ValueError)):
        create_flask_app(backend_lease_proof=proof)
    assert not target.exists(), "missing custody must not create a competing empty vault"
    assert len(calls) == 1


def test_legacy_wrong_password_refuses_before_schema_or_ciphertext_change(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Reject a wrong legacy vault password without schema or ciphertext mutation.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    import importlib.util
    import sqlite3
    from pathlib import Path
    from flinttrade_gateway.credentials import CredentialVaultInvalidError

    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location("_account_wrong_key_fixtures", root / "tests/credential_fixtures.py")
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    target = tmp_path / "credentials.db"
    original = fixtures.legacy_vault(target, "not-the-factory-password", account_id="Synthetic", broker="dhan")
    with pytest.raises(CredentialVaultInvalidError):
        create_flask_app(backend_lease_proof=backend_lease_factory())
    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT salt,encrypted_creds FROM accounts").fetchone() == original
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("accounts",)]


def test_new_authentication_requires_actual_sdk_attestation(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Refuse new authentication when installed SDK attestation is unavailable.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
    """
    from flinttrade_core import native_account_routes

    app, token, path, calls = production_app
    before = read_workspace_snapshot(path)
    monkeypatch.setattr(
        native_account_routes, "_native_sdk_not_ready_body", lambda adapter_id: {"status": "unavailable"}
    )
    response = connect(app, token)
    assert response.status_code == 503, response.json
    assert calls == []
    assert read_workspace_snapshot(path) == before


def _synthetic_resolvers():
    from datetime import UTC
    from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver
    from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver

    observed = datetime.now(UTC)
    until = observed + timedelta(hours=1)
    dhan = build_security_resolver(
        [
            {
                "EXCH_ID": "NSE",
                "SEGMENT": "D",
                "SECURITY_ID": "synthetic-id",
                "INSTRUMENT": "OPTIDX",
                "TRADING_SYMBOL": "NIFTY-JUN2099-22250-CE",
                "DISPLAY_NAME": "SYNTHETIC",
                "SYMBOL_NAME": "NIFTY",
                "UNDERLYING_SYMBOL": "NIFTY",
                "UNDERLYING_SECURITY_ID": "synthetic-underlying",
                "SM_EXPIRY_DATE": "2099-06-23",
                "STRIKE_PRICE": "22250",
                "OPTION_TYPE": "CE",
                "LOT_SIZE": "3",
                "TICK_SIZE": "5",
            }
        ],
        source_revision="synthetic-master-v1",
        observed_at=observed.timestamp(),
        valid_until=until.timestamp(),
    )
    epoch = int(datetime(2099, 6, 23, 10, tzinfo=UTC).timestamp()) - 315511200
    kotak = KotakContractResolver.from_records(
        [
            {
                "pSymbol": "71472",
                "pTrdSymbol": "NIFTY-JUN2099-22250-CE",
                "pExchSeg": "nse_fo",
                "pSymbolName": "NIFTY",
                "pOptionType": "CE",
                "pInstType": "OPTIDX",
                "lExpiryDate": str(epoch),
                "pExpiryDate": str(epoch),
                "dStrikePrice;": "2225000",
                "lLotSize": "3",
                "dTickSize": "5",
                "lPrecision": "2",
            }
        ],
        source="https://example.invalid/synthetic-master.csv",
        revision="synthetic-master-v1",
        observed_at=observed,
        valid_until=until,
    )
    return {"dhan": dhan, "kotakneo": kotak}


@pytest.mark.parametrize("production_app", ["with_resolvers"], indirect=True)
def test_factory_preserves_explicit_versioned_resolver_interfaces(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Retain the injected versioned contract resolver rather than acquire reference data.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    setup = app.extensions["flinttrade.account_setup"]
    snapshots = app.config["NATIVE_REFERENCE_RESOLVERS"]
    assert calls == []
    dhan = setup.drivers["dhan"].adapter
    kotak = setup.drivers["kotakneo"].adapter
    assert dhan._security_resolver is snapshots["dhan"]
    assert kotak._contract_resolver is snapshots["kotakneo"]
    assert dhan._security_resolver("NIFTY-JUN2099-22250-CE", "NFO") == "synthetic-id"
    assert dhan._security_resolver.contract("NIFTY-JUN2099-22250-CE", "NFO")["lot_size"] == 3
    assert callable(dhan._security_resolver.reverse)
    assert (
        kotak._contract_resolver.resolve("NIFTY-JUN2099-22250-CE", "NFO", now=datetime.now(ZoneInfo("UTC"))).lot_size
        == 3
    )
    assert (
        app.test_client().get("/api/v1/native/brokers", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    )
    assert calls == []
    assert connect(app, token).json["receipt"]["state"] == "committed"
    assert dhan._security_resolver is snapshots["dhan"]
    assert app.config.get("BROKER_ROUTER") is None


@pytest.mark.parametrize("authenticated", [False, True])
def test_default_factory_missing_reference_preflight_never_acquires_data(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
    authenticated: "bool",
) -> None:
    """Missing snapshots complete as unavailable, not a lazy master acquisition.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
        authenticated: Whether account setup precedes the missing-reference preflight.
    """
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    from flinttrade_core.models import Action, Exchange, Order, PriceType, Product
    from flinttrade_gateway.brokers import dhan_mapping

    app, token, path, calls = production_app
    setup = app.extensions["flinttrade.account_setup"]
    if authenticated:
        assert connect(app, token).json["receipt"]["state"] == "committed"
    before_calls = list(calls)
    before_workspace = read_workspace_snapshot(path)
    acquisitions = []

    def download(url):
        acquisitions.append(url)
        return "SEM_SMST_SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_TRADING_SYMBOL\n"

    monkeypatch.setattr("flinttrade_gateway.brokers.dhan._download_text", download)
    dhan = setup.drivers["dhan"].adapter
    kotak = setup.drivers["kotakneo"].adapter
    cash = Order(
        symbol="SYNTHETIC", exchange=Exchange.NSE, action=Action.BUY, product=Product.CNC, quantity="3",
    )
    option = Order(
        symbol="NIFTY-JUN2099-22250-CE",
        exchange=Exchange.NFO,
        action=Action.BUY,
        product=Product.NRML,
        pricetype=PriceType.LIMIT,
        quantity="3",
        price="7.25",
    )
    with pytest.raises(dhan_mapping.DhanMappingError):
        dhan.preflight_order(cash)
    with pytest.raises(dhan_mapping.DhanMappingError):
        dhan.preflight_order(option)
    with pytest.raises(UnsupportedCapabilityError, match="fresh exact listed contract"):
        kotak.preflight_order(option)
    assert kotak.preflight_order(cash) is None  # Pure ordinary mapping, not contract qualification.
    assert (
        app.test_client()
        .get(
            "/api/v1/native/brokers",
            headers={"Authorization": f"Bearer {token}"},
        )
        .status_code
        == 200
    )
    assert acquisitions == []
    assert calls == before_calls
    assert read_workspace_snapshot(path) == before_workspace
    assert app.config["NATIVE_REFERENCE_RESOLVERS"] == {}
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.parametrize("first_close_fails", [False, True])
def test_delivered_dhan_adapter_takes_zero_expiry_candidate_into_custody(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
    first_close_fails: "bool",
) -> None:
    """Capture zero-expiry candidate custody before verification and retry local close safely.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
        first_close_fails: Whether the first retained transport close raises.
    """
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    app, token, path, calls = production_app
    setup = app.extensions["flinttrade.account_setup"]
    descriptor = setup.drivers["dhan"]
    assert type(descriptor.adapter) is DhanAdapter
    assert descriptor.local_cleanup.__self__ is descriptor.adapter
    captured = []
    observations = []
    original = descriptor.adapter.liveness

    async def observe(session):
        observations.append((session.expires_at, setup.lifecycle.snapshot().cleanup_pending))
        captured.append(session)
        await original(session)

    monkeypatch.setattr(descriptor.adapter, "liveness", observe)
    assert connect(app, token).json["receipt"]["state"] == "committed"
    assert observations == [(0, 1)]
    assert len(captured) == 1 and captured[0].extra["provider_verified"] is True
    assert captured[0].expires_at == _PROFILE_EXPIRY.timestamp()
    if first_close_fails:
        transport = captured[0].extra["client"].dhan_http.session
        original_close = transport.close
        attempts = []

        def close():
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError("synthetic local pool failure")
            original_close()

        monkeypatch.setattr(transport, "close", close)
        assert not setup.lifecycle.close_and_drain(2)
        assert setup.lifecycle.snapshot().cleanup_pending == 1
        assert captured[0].extra["client"].dhan_http.session is transport
    assert setup.lifecycle.close_and_drain(2)
    assert len(calls) == 1
    assert captured[0].extra["locally_disposed"] is True
    assert "client" not in captured[0].extra


def test_dhan_provider_expiry_is_retained_without_reconnect_extension(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Preserve the observed provider expiry across explicit reconnect.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    selector = BrokerSelector("dhan", "Synthetic")
    first = app.config["REGISTRY"].snapshot_exact_state(selector)
    assert first.expires_at == _PROFILE_EXPIRY.timestamp()
    response = app.test_client().post(
        "/api/v1/native/accounts/dhan/Synthetic/login",
        json={},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
    )
    assert response.json["receipt"]["state"] == "committed", response.json
    assert app.config["REGISTRY"].snapshot_exact_state(selector).expires_at == first.expires_at
    assert [url for _, _, url in calls] == ["https://api.dhan.co/v2/profile"] * 2


def test_uninspected_native_custody_blocks_account_mutation(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
) -> None:
    """Refuse account mutation when incomplete native custody is present.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
    """
    app, token, path, calls = production_app
    owner = app.config["EXECUTION_SESSIONS"]
    marker = owner.path / "autonomy.sqlite.authority.json"
    assert not marker.exists()
    marker.write_text("synthetic incomplete native custody")
    marker.chmod(0o600)
    before = read_workspace_snapshot(path)
    try:
        response = connect(app, token)
        assert response.status_code == 503, response.json
        assert calls == []
        assert read_workspace_snapshot(path) == before
    finally:
        marker.unlink()  # only this test's incomplete synthetic canary


@pytest.mark.parametrize("production_app", ["with_acl"], indirect=True)
def test_retirement_revokes_held_read_before_its_response(
    production_app: "tuple[Flask, str, Path, list[tuple[requests.Session, str | None, str | None]]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Reject a held read's late response after its actual owner retires.

    Args:
        production_app: Normal factory app, operator token, workspace and inert HTTP call ledger.
        monkeypatch: Scoped replacements restored after this test.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    app, token, path, calls = production_app
    assert connect(app, token).json["receipt"]["state"] == "committed"
    setup = app.extensions["flinttrade.account_setup"]
    owner = setup.runtime.read_owner
    entered, release = threading.Event(), threading.Event()
    original = requests.Session.send

    def held(session, request, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(session, request, **kwargs)

    monkeypatch.setattr(requests.Session, "send", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            app.test_client().get,
            "/api/v1/native/accounts/dhan/Synthetic/funds",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            assert entered.wait(5)
            assert not setup.runtime.retire(0)
            assert setup.runtime.read_owner is None
        finally:
            release.set()
        response = pending.result(timeout=5)
    assert response.status_code in {403, 409}
    assert "data" not in response.json
    assert owner.close(timeout=2)
