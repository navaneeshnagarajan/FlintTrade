"""Fresh account setup through normal factory custody; external I/O is inert.

No human ACL is seeded: committed/session-present does not promise read access,
execution readiness, a default account, or complete account onboarding.
"""

from __future__ import annotations

from uuid import UUID, uuid4
import json

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from flinttrade_core import auth_routes
from flinttrade_core.account_setup import AccountSetupDriver
from flinttrade_core.app import create_flask_app
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.workspace_migrations import read_workspace_snapshot

from .account_lifecycle_test_support import SyntheticAdapter


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from flask import Flask
    from flinttrade_core.backend_instance import BackendLeaseProof
    from tests.flask_app_lifecycle import FactoryApps

pytestmark = pytest.mark.integration


@pytest.fixture
def setup_app(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
) -> "Iterator[tuple[Flask, SyntheticAdapter, str, Path]]":
    """Own a normal account-setup app backed by a disposable workspace and inert adapter.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.

    Yields:
        App, synthetic adapter, operator token and workspace, retained until existing owner cleanup.

    Raises:
        TimeoutError: The existing factory cleanup owner cannot drain within its bound.
    """
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    tmp_path.chmod(0o700)
    proof = backend_lease_factory()
    adapter = SyntheticAdapter()
    app = create_flask_app(
        backend_lease_proof=proof,
        account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup),
    )
    auth = app.config["AUTH_SERVICE"]
    auth.setup_account("operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = auth_routes._create_token("operator", mode="explore")
    yield app, adapter, token, tmp_path
    owned_flask_apps.close()


def test_fresh_connect_commits_managed_credentials_and_exact_replay(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Commit managed credentials once and replay the same receipt without writes.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
    """
    app, adapter, token, path = setup_app
    client = app.test_client()
    key = str(uuid4())
    body = {"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "synthetic-input"}}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
    selector = BrokerSelector("dhan", "Synthetic")
    vault = app.config["CREDENTIAL_STORE"]
    before = vault.selector_state(selector)
    before_workspace = read_workspace_snapshot(path)
    response = client.post("/api/v1/native/accounts", json=body, headers=headers)
    if response.status_code == 503:
        assert response.json == {"error": "broker_account_cutover_unavailable"}
        assert vault.selector_state(selector) == before
        assert read_workspace_snapshot(path) == before_workspace
        assert adapter.logins == 0
    assert response.status_code == 200, response.json
    assert response.headers["Cache-Control"] == "no-store"
    result = response.json
    assert result["receipt"]["operationId"] == key
    assert result["receipt"]["state"] == "committed"
    assert result["runtimeStatus"] == "session_present"
    service = app.extensions["flinttrade.account_setup"]
    operation = service.store.operation(UUID(key))
    assert operation.receipt is not None
    assert operation.witness == service.store.head()
    assert service.workspace.assert_coherent().as_dict()["_broker_account_store"] == operation.witness.to_dict()
    state = vault.selector_state(selector)
    assert state.present and state.credential_present and state.origin == "managed"
    assert state.version.generation == before.version.generation + 1
    assert vault.retrieve_for("dhan", "Synthetic") == {"token": "synthetic-replay"}
    assert b"synthetic-input" not in (path / "credentials.db").read_bytes()
    assert b"synthetic-replay" not in (path / "credentials.db").read_bytes()
    snapshot = read_workspace_snapshot(path)
    brokers = snapshot.as_dict()["brokers"]
    assert brokers["registered"] == ["dhan:Synthetic"]
    assert brokers["account_acls"] == {}
    assert brokers["execution"]["default"] == ""
    assert app.config["BROKER_ROUTER"] is None
    assert adapter.logins == 1
    writes = _vault_writes(monkeypatch)
    replay = client.post("/api/v1/native/accounts", json=body, headers=headers)
    assert replay.status_code == 200, replay.json
    assert replay.json["receipt"] == result["receipt"]
    assert adapter.logins == 1
    assert vault.selector_state(selector) == state
    assert read_workspace_snapshot(path) == snapshot
    assert service.store.operation(UUID(key)) == operation
    assert service.lifecycle.snapshot().active is False
    assert writes == []
    with app.app_context():
        assert auth_routes.decode_token(token)["mode"] == "explore"


def test_current_app_custody_is_rechecked_after_authentication(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
) -> None:
    """Reject a post-authentication registry substitution without committing credentials.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
    """
    app, adapter, token, path = setup_app
    service = app.extensions["flinttrade.account_setup"]
    before = read_workspace_snapshot(path)
    original = app.config["REGISTRY"]
    adapter.after_auth = lambda: app.config.__setitem__("REGISTRY", object())
    try:
        response = app.test_client().post(
            "/api/v1/native/accounts",
            json={"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "synthetic-input"}},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.json
        assert response.json["receipt"]["state"] == "rejected"
        assert service.credentials.selector_state(BrokerSelector("dhan", "Synthetic")).present is False
        assert read_workspace_snapshot(path) == before
        assert len(adapter.cleaned) == 1
    finally:
        app.config["REGISTRY"] = original


def _vault_writes(monkeypatch):
    from flinttrade_gateway import credentials

    original = credentials.open_sqlite
    writes = []

    def open_observed(*args, **kwargs):
        connection = original(*args, **kwargs)
        connection.set_trace_callback(
            lambda sql: (
                writes.append(sql)
                if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}
                else None
            )
        )
        return connection

    monkeypatch.setattr(credentials, "open_sqlite", open_observed)
    return writes


@pytest.mark.parametrize("change", ["body", "selector-case", "actor", "session", "scope"])
def test_key_conflicts_do_not_authenticate_or_write(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    change: "str",
) -> None:
    """Refuse changed idempotent requests before authentication or durable mutation.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        change: Named mutation applied to the otherwise valid control.
    """
    app, adapter, token, path = setup_app
    client = app.test_client()
    body = {"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "synthetic-input"}}
    key = str(uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
    assert client.post("/api/v1/native/accounts", json=body, headers=headers).status_code == 200
    before = read_workspace_snapshot(path)
    writes = _vault_writes(monkeypatch)
    if change == "body":
        body["credentials"] = {"token": "altered-synthetic"}
    elif change == "selector-case":
        body["account_id"] = "synthetic"
    else:
        with app.app_context():
            changed_token = auth_routes._create_token(
                "other" if change == "actor" else "operator",
                mode="explore",
                **({"scopes": ("admin.accounts.read",)} if change == "scope" else {}),
            )
        headers["Authorization"] = f"Bearer {changed_token}"
    response = client.post("/api/v1/native/accounts", json=body, headers=headers)
    assert response.status_code == (403 if change == "scope" else 409), response.json
    assert response.headers["Cache-Control"] == "no-store"
    assert writes == []
    assert adapter.logins == 1
    assert read_workspace_snapshot(path) == before


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "null",
        "[]",
        "false",
        "1",
        '"text"',
        '{"adapter_id":"dhan","adapter_id":"upstox","account_id":"Synthetic","credentials":{"token":"x"}}',
        '{"adapter_id":"dhan","account_id":"Synthetic","credentials":{"token":"x","token":"y"}}',
        *[
            json.dumps(
                {"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "x"}, "is_primary": v}
            )
            for v in (True, "false", 0, 1, 0.5, None)
        ],
        *[
            json.dumps({"adapter_id": "dhan", "account_id": v, "credentials": {"token": "x"}})
            for v in (True, 1.5, " Synthetic", "Synthetic/other", "")
        ],
        '{"adapter_id":"dhan","account_id":"Synthetic","accountId":"other","credentials":{"token":"x"}}',
        '{"adapter_id":"dhan","account_id":"Synthetic","actor":"operator","credentials":{"token":"x"}}',
        '{"adapter_id":"dhan","account_id":"Synthetic","expected_generation":1.2,"credentials":{"token":"x"}}',
        '{"adapter_id":"dhan","account_id":"Synthetic","credentials":{"token":NaN}}',
    ],
)
def test_raw_ingress_refuses_before_any_account_write(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    raw: "str",
) -> None:
    """Reject malformed or contradictory JSON before any account write.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        raw: Literal malformed or contradictory JSON body submitted before account mutation.
    """
    app, adapter, token, path = setup_app
    before = read_workspace_snapshot(path)
    writes = _vault_writes(monkeypatch)
    response = app.test_client().post(
        "/api/v1/native/accounts",
        data=raw,
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 400, response.json
    assert response.headers["Cache-Control"] == "no-store"
    assert writes == []
    assert adapter.logins == 0
    assert read_workspace_snapshot(path) == before


def _connect(client, token, *, key=None, body=None):
    return client.post(
        "/api/v1/native/accounts",
        json=body or {"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "synthetic-input"}},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid4())},
    )


def test_logout_during_real_auth_worker_prevents_commit(setup_app: "tuple[Flask, SyntheticAdapter, str, Path]") -> None:
    """Keep logout effective while the actual authentication worker is held.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
    """
    app, adapter, token, path = setup_app
    before = read_workspace_snapshot(path)
    adapter.auth_release.clear()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_connect, app.test_client(), token)
        try:
            assert adapter.auth_entered.wait(5)
            with app.app_context():
                payload = auth_routes.decode_token(token)
                auth_routes._revoke_jti(payload["jti"], payload["exp"])
        finally:
            adapter.auth_release.set()
        response = future.result(timeout=10)
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "rejected"
    assert app.config["CREDENTIAL_STORE"].selector_state(BrokerSelector("dhan", "Synthetic")).present is False
    assert read_workspace_snapshot(path) == before
    assert adapter.logins == 1 and len(adapter.cleaned) == 1


def test_factory_cleanup_retains_held_local_cleanup_then_retries_exact_owner(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Retain cleanup custody and the root lease until the same owner can drain.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    from flinttrade_core import app as app_module
    from flinttrade_core.backend_instance import (
        BackendInstanceAlreadyRunning,
        acquire_backend_instance_lease,
        require_backend_lease_proof,
    )

    app, adapter, token, _path = setup_app
    assert _connect(app.test_client(), token).status_code == 200
    service = app.extensions["flinttrade.account_setup"]
    owner = service.lifecycle
    proof = service.proof
    adapter.cleanup_release.clear()
    try:
        with pytest.raises(TimeoutError, match="broker account lifecycle did not drain"):
            app_module._shutdown_rotation_scheduler(app, timeout=0.02)
        assert app.extensions["flinttrade.broker_account_lifecycle_owner"] is owner
        assert owner.snapshot().cleanup_pending == 1
        assert owner.snapshot().accepting is False
        assert require_backend_lease_proof(proof) is proof
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        denied = _connect(app.test_client(), token)
        assert denied.status_code == 503
        assert adapter.logins == 1
    finally:
        adapter.cleanup_release.set()
        owned_flask_apps.close()
    assert owner.snapshot().cleanup_pending == 0
    assert len(adapter.cleaned) == 1
    assert require_backend_lease_proof(proof) is proof  # fixture still owns the root lease


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_existing_vault_family_is_not_opened_or_migrated(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
    suffix: "str",
) -> None:
    """Preserve every pre-existing SQLite family member before factory cutover.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
        suffix: SQLite family suffix whose existing bytes must remain untouched.
    """
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable

    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    proof = backend_lease_factory()
    target = tmp_path / ("credentials.db" + suffix)
    target.write_bytes(b"synthetic-preserved-old-storage")
    target.chmod(0o600)
    adapter = SyntheticAdapter()
    with pytest.raises(BrokerAccountCutoverUnavailable):
        create_flask_app(
            backend_lease_proof=proof, account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup)
        )
    assert target.read_bytes() == b"synthetic-preserved-old-storage"
    assert adapter.logins == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/native/oauth/start"),
        ("POST", "/api/v1/native/accounts/dhan/Synthetic/login"),
        ("POST", "/api/v1/native/accounts/dhan/Synthetic/set-primary"),
        ("DELETE", "/api/v1/native/accounts/dhan/Synthetic"),
        ("PUT", "/v1/rate-limits"),
        ("POST", "/admin/credentials/rotation/dhan/rotate-now"),
    ],
)
def test_composed_setup_does_not_open_any_unreplaced_mutation(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    method: "str",
    path: "str",
) -> None:
    """Keep unreplaced mutation routes frozen without account or vault writes.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        method: HTTP method of the still-frozen mutation route.
        path: Exact HTTP path of the still-frozen mutation route.
    """
    app, adapter, token, root = setup_app
    before = read_workspace_snapshot(root)
    writes = _vault_writes(monkeypatch)
    client = app.test_client()
    assert client.open(path, method=method, data="{", content_type="application/json").status_code == 401
    response = client.open(
        path, method=method, data="{", content_type="application/json", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 503, response.json
    assert response.json == {"error": "broker_account_cutover_unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert writes == [] and adapter.logins == 0
    assert read_workspace_snapshot(root) == before


def test_false_primary_is_supported_without_acl_or_read_activation(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
) -> None:
    """Accept an explicit non-primary account without granting ACL or read authority.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
    """
    app, adapter, token, path = setup_app
    response = _connect(
        app.test_client(),
        token,
        body={
            "adapter_id": "dhan",
            "account_id": "Synthetic",
            "credentials": {"token": "synthetic-input"},
            "is_primary": False,
        },
    )
    assert response.status_code == 200, response.json
    assert response.json["receipt"]["state"] == "committed"
    config = read_workspace_snapshot(path).as_dict()["brokers"]
    assert config["account_acls"] == {} and config["execution"]["default"] == ""
    assert (
        app.test_client()
        .get(
            "/api/v1/native/accounts/dhan/Synthetic/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        .status_code
        == 409
    )
    assert adapter.logins == 1


@pytest.mark.parametrize(
    "key",
    [
        "",
        "not-a-uuid",
        "123456781234423492341234567890ab",
        "12345678-1234-1234-9234-1234567890ab",
        "12345678-1234-4234-9234-1234567890AB",
    ],
)
def test_action_key_requires_literal_canonical_uuid4(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    key: "str",
) -> None:
    """Reject noncanonical action keys before authentication or storage writes.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        key: Malformed or noncanonical UUID spelling submitted unchanged.
    """
    app, adapter, token, path = setup_app
    writes = _vault_writes(monkeypatch)
    response = app.test_client().post(
        "/api/v1/native/accounts",
        json={"adapter_id": "dhan", "account_id": "Synthetic", "credentials": {"token": "x"}},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert response.status_code == 400
    assert writes == [] and adapter.logins == 0


def _uncertain_auth_child(path):
    """A retained unknown claim ends only with its owning disposable process.

    This is not clean-shutdown acceptance or a resolution workflow. The parent
    proves process exit releases the kernel lease; no in-process reset/retry is
    permitted merely to make this negative control tear down successfully.
    """
    import os
    import time
    from flinttrade_core.backend_instance import acquire_backend_instance_lease, require_backend_lease_proof
    from flinttrade_core.desktop import DesktopBackendShutdownIncomplete, _DesktopShutdownRecoveryOwner

    path = Path(path)
    path.mkdir(mode=0o700)
    (path / "master_password").write_text("synthetic-password")
    (path / "master_password").chmod(0o600)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(path)
    lease = acquire_backend_instance_lease()
    adapter = SyntheticAdapter()
    adapter.auth_release.clear()
    app = create_flask_app(
        backend_lease_proof=lease.proof, account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup)
    )
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = auth_routes._create_token("operator", mode="explore")
    service = app.extensions["flinttrade.account_setup"]
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_connect, app.test_client(), token, key=key)
        try:
            assert adapter.auth_entered.wait(5)
            response = future.result(timeout=40)
            assert response.status_code == 200, response.json
            assert response.json["receipt"]["state"] == "authentication_unknown"
            assert service.lifecycle.snapshot().workers == 1
            original = response.json["receipt"]
            replay = _connect(app.test_client(), token, key=key)
            assert replay.json["receipt"] == original
            assert adapter.logins == 1
            assert not service.lifecycle.close_and_drain(0.02)
            assert require_backend_lease_proof(lease.proof) is lease.proof
        finally:
            adapter.auth_release.set()
            future.result(timeout=5)
    # Retry joins the same real worker and cleans the late unpublished payload,
    # but it cannot erase the durable unknown claim or claim a clean shutdown.
    assert not service.lifecycle.close_and_drain(5)
    assert service.lifecycle.snapshot().workers == 0
    assert service.lifecycle.snapshot().cleanup_pending == 0
    assert len(adapter.cleaned) == 1
    assert service.store.operation(UUID(key)).receipt.state.value == "authentication_unknown"
    assert service.credentials.selector_state(BrokerSelector("dhan", "Synthetic")).present is False
    recovery = _DesktopShutdownRecoveryOwner(app)
    try:
        recovery.release(deadline=time.monotonic() + 0.05)
    except DesktopBackendShutdownIncomplete as error:
        assert error.recovery_owner is recovery
    else:
        raise AssertionError("unknown custody was silently released")
    assert require_backend_lease_proof(lease.proof) is lease.proof
    print("UNKNOWN_AUTH_RETAINED_UNTIL_PROCESS_EXIT", flush=True)
    os._exit(0)


@pytest.mark.slow
def test_unknown_auth_retains_worker_and_claim_without_reauthentication(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Retain unknown authentication custody until the isolated process exits.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
    """
    import subprocess
    import sys
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    path = tmp_path / "uncertain-workspace"
    root = Path(__file__).resolve().parents[4]
    code = (

            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from packages.core.core.tests.test_account_setup import _uncertain_auth_child\n"
            "_uncertain_auth_child(sys.argv[2])\n"

    )
    child = subprocess.run(
        [sys.executable, "-I", "-c", code, str(root), str(path)], capture_output=True, text=True, timeout=60
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert "UNKNOWN_AUTH_RETAINED_UNTIL_PROCESS_EXIT" in child.stdout
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(path))
    successor = acquire_backend_instance_lease()
    successor.release()


def test_receipt_replay_does_not_promise_current_runtime_availability(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Replay durable commit evidence without claiming a retired session is available.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
    """
    app, adapter, token, path = setup_app
    key = str(uuid4())
    client = app.test_client()
    first = _connect(client, token, key=key)
    assert first.json["runtimeStatus"] == "session_present"
    service = app.extensions["flinttrade.account_setup"]
    assert service.runtime.retire(2)
    writes = _vault_writes(monkeypatch)
    before = read_workspace_snapshot(path)
    replay = _connect(client, token, key=key)
    assert replay.status_code == 200
    assert replay.json["receipt"] == first.json["receipt"]
    assert replay.json["runtimeStatus"] == "session_unavailable"
    assert adapter.logins == 1 and writes == []
    assert read_workspace_snapshot(path) == before


@pytest.mark.parametrize("body_fails", [False, True])
def test_normal_factory_cleanup_releases_account_custody_before_root_lease(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    owned_flask_apps: "FactoryApps",
    body_fails: "bool",
) -> None:
    """Drain actual account owners before releasing the backend lease on either body outcome.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
        body_fails: Whether the fixture body raises before normal cleanup.
    """
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = acquire_backend_instance_lease()
    adapter = SyntheticAdapter()
    owner = None
    try:
        app = create_flask_app(
            backend_lease_proof=lease.proof, account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup)
        )
        owner = app.extensions["flinttrade.broker_account_lifecycle_owner"]
        app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
        with app.app_context():
            token = auth_routes._create_token("operator", mode="explore")
        assert _connect(app.test_client(), token).json["receipt"]["state"] == "committed"
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        if body_fails:
            raise ValueError("synthetic-body-failure")
    except ValueError as error:
        assert body_fails and str(error) == "synthetic-body-failure"
    finally:
        owned_flask_apps.close()
        assert owner is not None
        assert owner.snapshot().workers == owner.snapshot().cleanup_pending == owner.snapshot().live_owned == 0
        assert len(adapter.cleaned) == 1
        lease.release()
    successor = acquire_backend_instance_lease()
    successor.release()


def test_recognized_legacy_vault_is_preserved_before_constructor(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Refuse recognised legacy storage before its vault constructor is reached.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    import importlib.util
    import sys
    from flinttrade_core import account_setup
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable

    name = "_account_setup_credential_fixtures"
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[4] / "tests/credential_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    proof = backend_lease_factory()
    target = tmp_path / "credentials.db"
    module.legacy_vault(target, "synthetic-password", account_id="CaseA")
    original = target.read_bytes()
    opened = []

    def forbidden_constructor(*args, **kwargs):
        opened.append(True)
        raise AssertionError("legacy vault constructor was reached")

    monkeypatch.setattr(account_setup, "CredentialStore", forbidden_constructor)
    adapter = SyntheticAdapter()
    with pytest.raises(BrokerAccountCutoverUnavailable):
        create_flask_app(
            backend_lease_proof=proof, account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup)
        )
    assert opened == []
    assert target.read_bytes() == original


@pytest.mark.parametrize("composition", ["legacy-admission", "borrowed-registry"])
def test_partial_composition_rejects_legacy_bypass_and_borrowed_authorities(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    backend_lease_factory: "Callable[[], BackendLeaseProof]",
    owned_flask_apps: "FactoryApps",
    composition: "str",
) -> None:
    """Reject partial account composition rather than borrowing mutation authority.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        backend_lease_factory: Acquire the genuine backend lease for the selected test workspace.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
        composition: Borrowed or legacy authority arrangement that factory admission must refuse.
    """
    from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable
    from flinttrade_gateway.registry import create_owned_registry

    tmp_path.chmod(0o700)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    proof = backend_lease_factory()
    adapter = SyntheticAdapter()
    if composition == "legacy-admission":
        kwargs = {"broker_account_mutation_admission": lambda: None}
    else:
        registry, owner = create_owned_registry()
        kwargs = {"registry": registry, "registry_publication_owner": owner}
    with pytest.raises(BrokerAccountCutoverUnavailable):
        create_flask_app(
            backend_lease_proof=proof,
            account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup),
            **kwargs,
        )
    assert adapter.logins == 0
    assert not (tmp_path / "credentials.db").exists()


@pytest.mark.parametrize("token_kind", ["absent", "invalid", "non-full", "revoked"])
def test_authentication_refusal_precedes_malformed_body_and_is_not_cached(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    token_kind: "str",
) -> None:
    """Reject invalid authentication before body parsing and prevent response caching.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        token_kind: Absent, invalid, non-full or revoked authentication control.
    """
    app, adapter, token, path = setup_app
    headers = {}
    with app.app_context():
        if token_kind == "invalid":
            headers["Authorization"] = "Bearer invalid-synthetic-token"
        elif token_kind == "non-full":
            # A real reset token is not a full operator session.
            headers["Authorization"] = "Bearer " + auth_routes._create_reset_token("operator")
        elif token_kind == "revoked":
            payload = auth_routes.decode_token(token)
            auth_routes._revoke_jti(payload["jti"], payload["exp"])
            headers["Authorization"] = f"Bearer {token}"
    before = read_workspace_snapshot(path)
    writes = _vault_writes(monkeypatch)
    response = app.test_client().post(
        "/api/v1/native/accounts", headers=headers, data="{invalid", content_type="application/json"
    )
    assert response.status_code == 401, response.json
    assert response.headers.get("Cache-Control") == "no-store"
    assert adapter.logins == 0 and writes == []
    assert read_workspace_snapshot(path) == before


def test_failed_local_cleanup_retains_factory_owner_until_same_owner_retry(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
    owned_flask_apps: "FactoryApps",
) -> None:
    """Preserve the failed cleanup owner and lease until its successful retry.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
        owned_flask_apps: Retained factory apps and responses drained by their existing cleanup owners.
    """
    from flinttrade_core import app as app_module
    from flinttrade_core.backend_instance import require_backend_lease_proof

    app, adapter, token, _path = setup_app
    assert _connect(app.test_client(), token).json["receipt"]["state"] == "committed"
    service = app.extensions["flinttrade.account_setup"]
    owner = service.lifecycle
    calls = []
    wait = adapter.cleanup_release.wait

    def failed_disposal(*args, **kwargs):
        calls.append(True)
        raise OSError("synthetic-local-disposal-failed")

    monkeypatch.setattr(adapter.cleanup_release, "wait", failed_disposal)
    try:
        with pytest.raises(TimeoutError, match="broker account lifecycle did not drain"):
            app_module._shutdown_rotation_scheduler(app, timeout=0.1)
        assert calls
        assert app.extensions["flinttrade.broker_account_lifecycle_owner"] is owner
        assert owner.snapshot().cleanup_pending == 1
        assert require_backend_lease_proof(service.proof) is service.proof
    finally:
        monkeypatch.setattr(adapter.cleanup_release, "wait", wait)
        owned_flask_apps.close()
    assert owner.snapshot().cleanup_pending == 0
    assert len(adapter.cleaned) == 1


def test_conflicting_session_carriers_refuse_as_authentication_before_storage(
    setup_app: "tuple[Flask, SyntheticAdapter, str, Path]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Reject conflicting session carriers before touching account storage.

    Args:
        setup_app: Normal factory app, synthetic adapter, operator token and workspace path.
        monkeypatch: Scoped replacements restored after this test.
    """
    app, adapter, token, path = setup_app
    with app.app_context():
        other = auth_routes._create_token("other", mode="explore")
    before = read_workspace_snapshot(path)
    writes = _vault_writes(monkeypatch)
    response = app.test_client().post(
        "/api/v1/native/accounts",
        data="{invalid",
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}", "X-FlintTrade-Token": other, "Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 401, response.json
    assert response.headers["Cache-Control"] == "no-store"
    assert writes == []
    assert adapter.logins == 0
    assert read_workspace_snapshot(path) == before


def _fresh_probe_child(path, fault, cleanup_mode="ready"):
    """Observe unknown custody in its own process, never force-settle it."""
    import asyncio
    import os
    import threading
    from dataclasses import asdict
    from flinttrade_core import app as app_module
    from flinttrade_core.backend_instance import (
        BackendInstanceAlreadyRunning,
        acquire_backend_instance_lease,
        require_backend_lease_proof,
    )
    from flinttrade_gateway import native_login

    path = Path(path)
    path.mkdir(mode=0o700)
    (path / "master_password").write_text("synthetic-password")
    (path / "master_password").chmod(0o600)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(path)

    class ProbeAdapter(SyntheticAdapter):
        def __init__(self):
            super().__init__()
            self.probes = 0
            self.exports = 0
            self.cleanup_calls = 0
            self.cleanup_entered = threading.Event()
            self.cleanup_mode = cleanup_mode
            if cleanup_mode == "held":
                self.cleanup_release.clear()
            self.failure = (
                RuntimeError("synthetic-replay-export-failed")
                if fault == "replay"
                else asyncio.CancelledError("synthetic-probe-cancelled")
                if fault == "cancelled"
                else TimeoutError("synthetic-liveness-uncertain")
            )

        async def liveness(self, session):
            assert session is self.sessions[0]
            self.probes += 1
            if fault in {"timeout", "cancelled"}:
                raise self.failure

        def replay_credentials(self, credentials, session):
            assert session is self.sessions[0]
            self.exports += 1
            if fault == "replay":
                raise self.failure
            return super().replay_credentials(credentials, session)

        def cleanup(self, payload):
            assert payload is self.sessions[0]
            self.cleanup_calls += 1
            self.cleanup_entered.set()
            if self.cleanup_mode == "failed":
                raise OSError("synthetic-local-cleanup-failed")
            if self.cleanup_mode == "non-none":
                return False
            return super().cleanup(payload)

    lease = acquire_backend_instance_lease()
    adapter = ProbeAdapter()
    app = create_flask_app(
        backend_lease_proof=lease.proof,
        account_setup_driver=AccountSetupDriver("dhan", adapter, adapter.cleanup),
    )
    app.config["AUTH_SERVICE"].setup_account("operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = auth_routes._create_token("operator", mode="explore")
    service = app.extensions["flinttrade.account_setup"]
    owner = service.lifecycle
    selector = BrokerSelector("dhan", "Synthetic")
    before = service.credentials.selector_state(selector)
    workspace = read_workspace_snapshot(path)
    key = str(uuid4())
    client = app.test_client()
    if fault == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            _connect(client, token, key=key)
    response = _connect(client, token, key=key)
    state = service.credentials.selector_state(selector)
    operation = service.store.operation(UUID(key))
    registry = service.registry.snapshot_exact_state(selector)
    print(
        "FRESH_PROBE_OBSERVATION "
        + json.dumps(
            {
                "fault": fault,
                "status": response.status_code,
                "body": response.json,
                "lifecycle": asdict(owner.snapshot()),
                "logins": adapter.logins,
                "probes": adapter.probes,
                "exports": adapter.exports,
                "cleaned": len(adapter.cleaned),
                "generation_before": before.version.generation,
                "generation_after": state.version.generation,
                "workspace_unchanged": read_workspace_snapshot(path) == workspace,
                "witness_present": operation.witness is not None,
                "registry_bound": registry is not None and registry.binding is not None,
                "global_candidate_count": sum(
                    c.session is adapter.sessions[0] for c in native_login._QUARANTINED_CANDIDATES
                ),
            }
        ),
        flush=True,
    )
    assert response.status_code == 200, response.json
    assert response.headers["Cache-Control"] == "no-store"
    expected = "committed" if fault == "success" else "authentication_unknown"
    assert response.json["receipt"]["state"] == expected, response.json
    assert response.json["runtimeStatus"] == ("session_present" if fault == "success" else "blocked")
    assert adapter.logins == adapter.probes == 1
    if fault == "success":
        assert state.version.generation == before.version.generation + 1
        assert state.origin == "managed" and state.credential_present
        assert operation.witness == service.store.head()
        assert registry.binding is not None
    else:
        assert state == before
        assert read_workspace_snapshot(path) == workspace
        assert operation.witness is None
        assert registry is None or registry.binding is None
        assert owner.snapshot().active and owner.snapshot().workers == 0
        assert owner.snapshot().cleanup_pending == 1
        # Passive identity observations: no completion/settlement is manufactured.
        attempt = service._coordinators[UUID(key)]._attempts[UUID(key)]
        lease_token, ticket, retained = owner._candidates[id(adapter.sessions[0])]
        assert lease_token is attempt.lease
        assert retained.raw_payload is retained.payload is adapter.sessions[0]
        assert retained.cleanup.__self__.lifecycle is owner
        workers = owner._operations[attempt.lease].workers
        assert any(w.done() and w.exception() is adapter.failure for w in workers)
        assert not any(c.session is adapter.sessions[0] for c in native_login._QUARANTINED_CANDIDATES)
    with pytest.MonkeyPatch.context() as patch:
        writes = _vault_writes(patch)
        replay = _connect(client, token, key=key)
        assert replay.status_code == 200 and replay.json == response.json
        assert writes == [] and adapter.logins == adapter.probes == 1
        assert service.credentials.selector_state(selector) == state
        assert service.store.operation(UUID(key)) == operation
        if fault != "success":
            denied = _connect(client, token)
            assert denied.status_code == 409
            assert writes == [] and adapter.logins == 1
    if fault == "success":
        app_module._shutdown_rotation_scheduler(app, timeout=5)
    else:
        with pytest.raises(TimeoutError, match="broker account lifecycle did not drain"):
            app_module._shutdown_rotation_scheduler(app, timeout=0.1)
        assert app.extensions["flinttrade.broker_account_lifecycle_owner"] is owner
        assert owner.snapshot().active
        if cleanup_mode != "ready":
            try:
                assert adapter.cleanup_entered.wait(5)
                assert owner.snapshot().cleanup_pending == 1
                assert adapter.cleaned == []
                assert owner._candidates[id(adapter.sessions[0])] == (lease_token, ticket, retained)
                assert adapter.cleanup_calls == 1
                print(
                    "FRESH_PROBE_RETRY_PENDING "
                    + json.dumps(
                        {
                            "fault": fault,
                            "cleanup_mode": cleanup_mode,
                            "same_ticket": True,
                            "same_owner": True,
                            "calls": adapter.cleanup_calls,
                            "lifecycle": asdict(owner.snapshot()),
                        }
                    ),
                    flush=True,
                )
            finally:
                adapter.cleanup_mode = "ready"
                adapter.cleanup_release.set()
            with pytest.raises(TimeoutError, match="broker account lifecycle did not drain"):
                app_module._shutdown_rotation_scheduler(app, timeout=5)
            assert app.extensions["flinttrade.broker_account_lifecycle_owner"] is owner
            assert adapter.cleanup_calls == (1 if cleanup_mode == "held" else 2)
        assert service.store.operation(UUID(key)).receipt == operation.receipt
        assert require_backend_lease_proof(lease.proof) is lease.proof
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
    print(
        "FRESH_PROBE_CLEANUP "
        + json.dumps(
            {
                "fault": fault,
                "cleaned": len(adapter.cleaned),
                "same_session": len(adapter.cleaned) == 1 and adapter.cleaned[0] is adapter.sessions[0],
                "lifecycle": asdict(owner.snapshot()),
            }
        ),
        flush=True,
    )
    # Local disposal does not resolve or release the unknown durable claim.
    assert len(adapter.cleaned) == 1 and adapter.cleaned[0] is adapter.sessions[0]
    assert owner.snapshot().cleanup_pending == 0
    assert not any(c.session is adapter.sessions[0] for c in native_login._QUARANTINED_CANDIDATES)
    assert app.config["BROKER_ROUTER"] is None
    brokers = read_workspace_snapshot(path).as_dict()["brokers"]
    assert brokers["account_acls"] == {} and brokers["execution"]["default"] == ""
    with app.app_context():
        assert auth_routes.decode_token(token)["mode"] == "explore"
    print("FRESH_PROBE_CHILD_EXIT", flush=True)
    os._exit(0)


@pytest.mark.parametrize(
    "fault,cleanup_mode",
    [
        ("timeout", "ready"),
        ("replay", "ready"),
        ("success", "ready"),
        ("replay", "failed"),
        ("replay", "held"),
        ("replay", "non-none"),
        ("cancelled", "ready"),
    ],
)
def test_fresh_connect_requires_successful_liveness(
    tmp_path: "Path",
    monkeypatch: "pytest.MonkeyPatch",
    fault: "str",
    cleanup_mode: "str",
) -> None:
    """Exercise fresh verification and retained cleanup through the isolated auth child.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.
        monkeypatch: Scoped replacements restored after this test.
        fault: Authentication/probe outcome exercised in the isolated child.
        cleanup_mode: Local cleanup disposition exercised after authentication.
    """
    import subprocess
    import sys
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    path = tmp_path / "fresh-probe"
    root = Path(__file__).resolve().parents[4]
    code = (

            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from packages.core.core.tests.test_account_setup import _fresh_probe_child\n"
            "_fresh_probe_child(sys.argv[2], sys.argv[3], sys.argv[4])\n"

    )
    child = subprocess.run(
        [sys.executable, "-I", "-c", code, str(root), str(path), fault, cleanup_mode],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(child.stdout, child.stderr)
    assert child.returncode == 0, child.stdout + child.stderr
    assert "FRESH_PROBE_CHILD_EXIT" in child.stdout
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(path))
    successor = acquire_backend_instance_lease()
    successor.release()
