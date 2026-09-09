"""Tests for single-backend process ownership."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import threading
from contextlib import suppress
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

import pytest
from flask import Flask


def test_live_proof_watch_closes_admission_before_lifecycle_callback(backend_lease_proof):
    from flinttrade_core.app import _BackendLeaseRuntimeWatch
    from flinttrade_core.backend_instance import BackendLeaseUnavailable, require_backend_lease_proof

    app = Flask("synthetic-revocation")
    events = []
    stopped = threading.Event()

    def revoke(*, timeout):
        with pytest.raises(BackendLeaseUnavailable):
            require_backend_lease_proof(backend_lease_proof)
        assert app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        events.append("router-revoked")
        return True

    def shutdown():
        assert events == ["router-revoked"]
        assert app.config["BACKEND_LEASE_READY"] is False
        events.append("lifecycle-shutdown")
        stopped.set()

    app.config["BROKER_ROUTER"] = SimpleNamespace(revoke_and_drain=revoke)
    watch = _BackendLeaseRuntimeWatch(app, backend_lease_proof, shutdown)
    watch.start()
    try:
        backend_lease_proof.revoke()
        assert stopped.wait(1)
        assert events == ["router-revoked", "lifecycle-shutdown"]
    finally:
        assert watch.stop(timeout=1)


def test_stopped_proof_watch_cannot_request_late_shutdown(backend_lease_proof):
    from flinttrade_core.app import _BackendLeaseRuntimeWatch

    called = threading.Event()
    watch = _BackendLeaseRuntimeWatch(Flask("synthetic-stop"), backend_lease_proof, called.set)
    watch.start()
    assert watch.stop(timeout=1)
    backend_lease_proof.revoke()
    assert not called.is_set()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_wsgi_revocation_snapshots_current_owners_then_requests_host_shutdown(
    monkeypatch, backend_lease_proof, cleanup_fails,
):
    import flinttrade_core.app as app_module
    import flinttrade_core.desktop as desktop_module

    app = Flask("synthetic-wsgi-revocation")
    events = []
    terminated = threading.Event()
    cleanup_attempted = threading.Event()

    class RecoveryOwner:
        def __init__(self, candidate):
            assert candidate is app
            events.append("snapshot-current-owners")

        def release(self, *, deadline):
            assert app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
            assert app.config["BACKEND_LEASE_READY"] is False
            if cleanup_fails:
                events.append("owners-retained")
                cleanup_attempted.set()
                raise desktop_module.DesktopBackendShutdownIncomplete(
                    "Synthetic retained cleanup", recovery_owner=self,
                )
            events.append("owners-drained")

    def shutdown():
        assert events == ["snapshot-current-owners", "owners-drained"]
        events.append("host-shutdown")
        terminated.set()

    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", lambda: _FakeLease([], backend_lease_proof))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_: app)
    monkeypatch.setattr(desktop_module, "_DesktopShutdownRecoveryOwner", RecoveryOwner)
    try:
        assert app_module._get_wsgi_app(shutdown_callback=shutdown) is app
        assert events == []
        backend_lease_proof.revoke()
        if cleanup_fails:
            assert cleanup_attempted.wait(1)
            assert app_module._stop_backend_lease_watch(app, timeout=1)
            assert not terminated.is_set()
            assert events == ["snapshot-current-owners", "owners-retained"]
            assert isinstance(app.extensions["flinttrade.wsgi_shutdown_owner"], RecoveryOwner)
        else:
            assert terminated.wait(1)
            assert events[-1] == "host-shutdown"
    finally:
        assert app_module._stop_backend_lease_watch(app, timeout=1)


@pytest.mark.skipif(os.name != "posix", reason="actual POSIX flock failure contract")
@pytest.mark.parametrize("stage", ["stat", "proof"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_post_acquisition_failure_releases_or_retains_exact_kernel_owner(
    tmp_path, monkeypatch, stage, cleanup_fails,
):
    import flinttrade_core.backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    descriptors = []
    original_open = os.open
    original_stat = Path.stat
    retained_before = tuple(module._RETAINED_FAILED_LEASES)

    def record_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        if str(args[0]).endswith("backend_instance.lock"):
            descriptors.append(descriptor)
        return descriptor

    def fail_stat(path, *args, **kwargs):
        if path.name == "backend_instance.lock":
            raise PermissionError("injected post-acquisition failure")
        return original_stat(path, *args, **kwargs)

    def fail_proof(*args, **kwargs):
        raise PermissionError("injected post-acquisition failure")

    try:
        with monkeypatch.context() as fault:
            fault.setattr(os, "open", record_open)
            fault.setattr(Path, "stat", fail_stat) if stage == "stat" else fault.setattr(
                module, "BackendLeaseProof", fail_proof,
            )
            if cleanup_fails:
                fault.setattr(module._PosixBackendFileLease, "release", lambda self: (_ for _ in ()).throw(
                    OSError("injected cleanup failure"),
                ))
            with pytest.raises((PermissionError, OSError)):
                module.acquire_backend_instance_lease()
        retained = [owner for owner in module._RETAINED_FAILED_LEASES if owner not in retained_before]
        if cleanup_fails:
            assert len(retained) == 1
            with pytest.raises(module.BackendInstanceAlreadyRunning):
                module.acquire_backend_instance_lease()
            module.release_retained_backend_instance_lease(retained[0])
        else:
            with pytest.raises(OSError):
                os.fstat(descriptors[0])
        successor = module.acquire_backend_instance_lease()
        successor.release()
    finally:
        for owner in tuple(module._RETAINED_FAILED_LEASES):
            if owner not in retained_before:
                module.release_retained_backend_instance_lease(owner)
        for descriptor in descriptors:
            with suppress(OSError):
                os.close(descriptor)


@pytest.mark.parametrize("stage", ["ContractManager", "create_owned_registry", "_initialise_rag_runtime"])
def test_partial_standalone_construction_closes_actual_vault_before_lease_release(monkeypatch, stage):
    import flinttrade_core.app as module
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    def fail(*args, **kwargs):
        raise RuntimeError("injected late constructor failure")

    runtime = module.FlintTradeApp()
    monkeypatch.setattr(module, stage, fail)
    try:
        with pytest.raises(RuntimeError, match="injected late constructor failure"):
            runtime.run()
        assert runtime.credential_store._poisoned is True
        assert runtime._stop_completed is True
        successor = acquire_backend_instance_lease()
        successor.release()
    finally:
        if runtime.credential_store is not None:
            runtime.credential_store.close()


def test_proofless_factory_does_not_construct_scheduler_or_rotation_owners(monkeypatch):
    import flinttrade_core.app as module
    import flinttrade_engine.scheduler as scheduling
    import flinttrade_gateway.credentials_rotation as rotation
    from apscheduler.schedulers import background

    def forbidden(*args, **kwargs):
        pytest.fail("proofless construction acquired scheduling ownership")

    for owner in ("TimeScheduler", "CronStrategyScheduler"):
        monkeypatch.setattr(scheduling, owner, forbidden)
    monkeypatch.setattr(background, "BackgroundScheduler", forbidden)
    monkeypatch.setattr(rotation, "CredentialsRotator", forbidden)
    app = module.create_flask_app()
    assert app.config.get("TIME_SCHEDULER") is None
    assert app.config.get("CRON_SCHEDULER") is None
    assert app.config.get("ROTATION_SCHEDULER") is None
    assert app.config.get("CREDENTIALS_ROTATOR") is None
    response = app.test_client().get("/admin/credentials/rotation/status")
    assert response.status_code == 503
    assert response.json["error"] == "backend_lease_unavailable"


def test_partial_vault_close_failure_retains_lease_until_exact_owner_recovers(monkeypatch):
    import flinttrade_core.app as module
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    runtime = module.FlintTradeApp()
    allow_close = False
    original_close = module.CredentialStore.close

    def close(store):
        if not allow_close:
            raise OSError("injected vault close failure")
        original_close(store)

    def fail(*args, **kwargs):
        raise RuntimeError("injected late constructor failure")

    monkeypatch.setattr(module.CredentialStore, "close", close)
    monkeypatch.setattr(module, "ContractManager", fail)
    try:
        with pytest.raises(RuntimeError, match="injected late constructor failure"):
            runtime.run()
        assert runtime._stop_completed is False
        assert runtime._startup_recovery_pending is True
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        allow_close = True
        runtime.retry_recovery()
        assert runtime.credential_store._poisoned is True
        assert runtime._stop_completed is True
        successor = acquire_backend_instance_lease()
        successor.release()
    finally:
        allow_close = True
        if runtime._requires_runtime_recovery():
            runtime.retry_recovery()


def test_kernel_lease_proof_is_opaque_and_revoked_before_unlock(tmp_path, monkeypatch):
    import flinttrade_core.backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = module.acquire_backend_instance_lease()
    try:
        assert hasattr(lease, "proof"), "kernel ownership must mint an explicit live proof"
        proof = lease.proof
        assert module.require_backend_lease_proof(proof) is proof
        assert proof.incarnation.version == 4
        for forged in (None, True, object(), object.__new__(type(proof))):
            with pytest.raises(module.BackendLeaseUnavailable):
                module.require_backend_lease_proof(forged)
        original_release = lease._raw_lease.release

        def observe_release():
            with pytest.raises(module.BackendLeaseUnavailable):
                module.require_backend_lease_proof(proof)
            original_release()

        monkeypatch.setattr(lease._raw_lease, "release", observe_release)
    finally:
        lease.release()
    with pytest.raises(module.BackendLeaseUnavailable):
        module.require_backend_lease_proof(proof)


def test_manually_wrapped_lock_cannot_mint_backend_proof():
    import flinttrade_core.backend_instance as module

    lease = module.BackendInstanceLease(SimpleNamespace(release=lambda: None))
    assert hasattr(type(lease), "proof"), "a proof must distinguish kernel acquisition from a wrapper"
    with pytest.raises(module.BackendLeaseUnavailable):
        _ = lease.proof


def test_unissued_handoff_cannot_mint_a_proof():
    import flinttrade_core.backend_instance as module

    forged = object.__new__(module.BackendLeaseHandoff)
    with pytest.raises(module.BackendLeaseUnavailable):
        forged.claim()


def test_same_process_filelock_branch_requires_live_kernel_owner(tmp_path, monkeypatch):
    """Exercise the Windows ownership contract; native byte locks remain CI work."""
    import flinttrade_core.backend_instance as module

    class SameProcessPlatform:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(module, "os", SameProcessPlatform())
    lease = module.acquire_backend_instance_lease()
    proof = lease.proof
    try:
        assert module.require_backend_lease_proof(proof) is proof
        lease._raw_lease.release()
        with pytest.raises(module.BackendLeaseUnavailable):
            module.require_backend_lease_proof(proof)
    finally:
        lease.release()


def test_factory_rejects_forged_proof_and_proofless_injected_broker_owner():
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.backend_instance import BackendLeaseUnavailable

    with pytest.raises(BackendLeaseUnavailable):
        create_flask_app(backend_lease_proof=True)
    with pytest.raises(BackendLeaseUnavailable):
        create_flask_app(client=object())


def test_backend_proof_cannot_construct_a_different_workspaces_runtime(tmp_path, monkeypatch):
    from flinttrade_core import backend_instance

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "first"))
    lease = backend_instance.acquire_backend_instance_lease()
    proof = lease.proof
    try:
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "second"))
        with pytest.raises(backend_instance.BackendLeaseUnavailable):
            backend_instance.require_backend_lease_proof(proof)
    finally:
        lease.release()


def test_standalone_construction_defers_broker_owners(monkeypatch):
    import flinttrade_core.app as module

    def forbidden(*args, **kwargs):
        pytest.fail("broker authority constructed before backend ownership")

    monkeypatch.setattr(module, "OpenAlgoClient", forbidden)
    monkeypatch.setattr(module, "CredentialStore", forbidden)
    monkeypatch.setattr(module, "create_owned_registry", forbidden)
    runtime = module.FlintTradeApp()
    assert runtime.client is None
    assert runtime.registry is None
    assert runtime.scheduler is None


def test_standalone_partial_construction_closes_owners_before_releasing_lease(monkeypatch):
    import flinttrade_core.app as module
    from flinttrade_core.backend_instance import require_backend_lease_proof

    runtime = module.FlintTradeApp()
    events = []

    async def close_client():
        require_backend_lease_proof(runtime._backend_lease_proof)
        events.append("client-closed")

    def initialise():
        runtime.client = SimpleNamespace(close=close_client)
        runtime.audit = SimpleNamespace(close=lambda: events.append("audit-closed"))
        raise RuntimeError("construction interrupted")

    monkeypatch.setattr(runtime, "_initialise_runtime", initialise)
    with pytest.raises(RuntimeError, match="construction interrupted"):
        runtime.run()
    assert events == ["client-closed", "audit-closed"]


def test_proofless_flask_factory_serves_without_broker_authorities(monkeypatch):
    import flinttrade_core.app as module

    def forbidden(*args, **kwargs):
        pytest.fail("proofless factory constructed broker authority")

    monkeypatch.setattr(module, "CredentialStore", forbidden)
    monkeypatch.setattr(module, "create_owned_registry", forbidden)
    monkeypatch.setattr(module, "OpenAlgoClient", forbidden)
    app = module.create_flask_app()
    assert app.config["REGISTRY"] is None
    assert app.config["CREDENTIAL_STORE"] is None
    assert app.config["CLIENT"] is None
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BACKEND_LEASE_READY"] is False
    assert app.test_client().get("/healthz").status_code == 200


def test_desktop_validates_live_proof_before_its_runtime_factory(tmp_path, monkeypatch):
    import flinttrade_core.backend_instance as ownership
    import flinttrade_core.desktop as desktop

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = ownership.acquire_backend_instance_lease()
    calls = []

    def serve(port, **kwargs):
        calls.append(ownership.require_backend_lease_proof(kwargs["backend_lease_proof"]))

    monkeypatch.setattr(desktop, "_serve_owned", serve)
    try:
        desktop.serve(0, backend_lease_proof=lease.proof)
        assert calls == [lease.proof]
        with pytest.raises(ownership.BackendLeaseUnavailable):
            desktop.serve(0, backend_lease_proof=True)
        proof = lease.proof
    finally:
        lease.release()
    with pytest.raises(ownership.BackendLeaseUnavailable):
        desktop.serve(0, backend_lease_proof=proof)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="real POSIX inherited anonymous pipe")
@pytest.mark.parametrize("termination", ["release", "revoke"])
def test_guardian_handoff_binds_child_and_revokes_on_parent_release(tmp_path, monkeypatch, termination):
    import flinttrade_core.backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = module.acquire_backend_instance_lease()
    assert hasattr(module, "prepare_backend_lease_handoff"), "guardian ownership needs a one-time transport"
    handoff = module.prepare_backend_lease_handoff(lease)
    result_read, result_write = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(result_read)
        try:
            proof = handoff.claim()
            module.require_backend_lease_proof(proof)
            with pytest.raises(module.BackendLeaseUnavailable):
                handoff.claim()
            os.write(result_write, b"live")
            assert proof.wait_revoked(5), "EOF must revoke without another request"
            with pytest.raises(module.BackendLeaseUnavailable):
                module.require_backend_lease_proof(proof)
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(result_write)
    try:
        handoff.publish(child)
        import select
        assert select.select([result_read], [], [], 5)[0]
        assert os.read(result_read, 4) == b"live"
        if termination == "release":
            lease.release()
        else:
            lease.proof.revoke()
        assert os.waitpid(child, 0)[1] == 0
    finally:
        lease.release()
        os.close(result_read)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="real POSIX inherited transport")
@pytest.mark.parametrize("tamper", ["nonce", "owner", "child", "inherited_local_proof"])
def test_guardian_rejects_substituted_handoff_and_forked_local_proof(tmp_path, monkeypatch, tamper):
    import flinttrade_core.backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = module.acquire_backend_instance_lease()
    local_proof = lease.proof
    handoff = module.prepare_backend_lease_handoff(lease)
    child = os.fork()
    if child == 0:
        try:
            if tamper == "nonce":
                handoff._nonce = b"x" * 32
            elif tamper == "owner":
                handoff._owner_pid += 1
            try:
                if tamper == "inherited_local_proof":
                    module.require_backend_lease_proof(local_proof)
                else:
                    handoff.claim()
            except module.BackendLeaseUnavailable:
                os._exit(0)
            os._exit(1)
        except BaseException:
            os._exit(2)
    try:
        handoff.publish(child + 1 if tamper == "child" else child)
        with pytest.raises(module.BackendLeaseUnavailable):
            handoff.publish(child)
        assert os.waitpid(child, 0)[1] == 0
    finally:
        lease.release()


def test_replaced_kernel_lock_revokes_live_guardian_channel(tmp_path, monkeypatch):
    import flinttrade_core.backend_instance as module

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = module.acquire_backend_instance_lease()
    proof = lease.proof
    try:
        (tmp_path / "backend_instance.lock").unlink()
        (tmp_path / "backend_instance.lock").touch()
        assert proof.wait_revoked(2), "loss of the kernel-owned inode must revoke without a request"
    finally:
        lease.release()


_HOLD_BACKEND_LEASE = """
import os
import sys
import time
from pathlib import Path

from flinttrade_core.backend_instance import acquire_backend_instance_lease

workspace, entered, release = map(Path, sys.argv[1:4])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
lease = acquire_backend_instance_lease()
try:
    entered.write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release backend lease holder")
        time.sleep(0.01)
finally:
    lease.release()
"""


_TRY_BACKEND_LEASE = """
import os
import sys
from pathlib import Path

from flinttrade_core.backend_instance import (
    BackendInstanceAlreadyRunning,
    acquire_backend_instance_lease,
)

workspace = Path(sys.argv[1])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
try:
    lease = acquire_backend_instance_lease()
except BackendInstanceAlreadyRunning:
    raise SystemExit(23)
lease.release()
"""


_FORKED_CHILD_DESTRUCTOR_HOLDER = """
import gc
import os
import select
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

from flinttrade_core.backend_instance import acquire_backend_instance_lease

workspace, entered, release = map(Path, sys.argv[1:4])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
lease = acquire_backend_instance_lease()
ready_read, ready_write = os.pipe()
child_pid = os.fork()

if child_pid == 0:
    os.close(ready_read)
    try:
        del lease
        gc.collect()
        os.write(ready_write, b"1")
    finally:
        os._exit(0)

os.close(ready_write)
try:
    readable, _, _ = select.select([ready_read], [], [], 5.0)
    if not readable or os.read(ready_read, 1) != b"1":
        raise RuntimeError("forked child did not destroy its inherited lease")
    waited_pid, status = os.waitpid(child_pid, 0)
    child_pid = 0
    if waited_pid <= 0 or os.waitstatus_to_exitcode(status) != 0:
        raise RuntimeError("forked child exited unsuccessfully")
    entered.write_text("entered", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test did not release backend lease holder")
        time.sleep(0.01)
finally:
    if child_pid:
        with suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)
        os.waitpid(child_pid, 0)
    os.close(ready_read)
    lease.release()
"""


_FORKED_PRELOADED_WSGI_REQUEST = """
import os
import sys
from pathlib import Path

from flask import Flask

import flinttrade_core.app as app_module

workspace = Path(sys.argv[1])
os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace)
route_calls = []
flask_app = Flask("preloaded-wsgi-request")

@flask_app.get("/probe")
def probe():
    route_calls.append(os.getpid())
    return "served"

app_module._APP_CACHE = None
app_module._APP_CACHE_PID = None
app_module._WSGI_BACKEND_LEASE = None
app_module.create_flask_app = lambda **kwargs: flask_app
preloaded_app = app_module._get_wsgi_app(shutdown_callback=lambda: None)
owner_response = preloaded_app.test_client().get("/probe")
if owner_response.status_code != 200 or route_calls != [os.getpid()]:
    app_module._WSGI_BACKEND_LEASE.release()
    raise SystemExit(40)
route_calls.clear()
child_pid = os.fork()

if child_pid == 0:
    try:
        response = preloaded_app.test_client().get("/probe")
        if response.status_code != 503:
            os._exit(41)
        if b"inherited WSGI app" not in response.data:
            os._exit(42)
        if route_calls:
            os._exit(43)
    except BaseException:
        os._exit(44)
    os._exit(0)

_, status = os.waitpid(child_pid, 0)
try:
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise SystemExit(os.WEXITSTATUS(status) if os.WIFEXITED(status) else 45)
finally:
    app_module._WSGI_BACKEND_LEASE.release()
"""


def _wait_for_marker(marker: Path, process: subprocess.Popen[str], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not marker.exists():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"backend lease holder exited early (code {process.returncode}): {stdout}{stderr}")
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for backend lease holder")
        time.sleep(0.01)


@pytest.mark.unit
def test_live_backend_process_blocks_a_second_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import (
        BackendInstanceAlreadyRunning,
        acquire_backend_instance_lease,
    )

    entered = tmp_path / "entered"
    release = tmp_path / "release"
    env = os.environ.copy()
    env["FLINTTRADE_WORKSPACE_DIR"] = str(tmp_path)
    process = subprocess.Popen(
        [sys.executable, "-c", _HOLD_BACKEND_LEASE, str(tmp_path), str(entered), str(release)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_marker(entered, process)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

        with pytest.raises(
            BackendInstanceAlreadyRunning,
            match="another FlintTrade backend",
        ) as raised:
            acquire_backend_instance_lease()
        assert raised.value.__cause__ is None
    finally:
        release.touch(exist_ok=True)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5.0)

    stdout, stderr = process.communicate()
    assert process.returncode == 0, stdout + stderr


@pytest.mark.unit
def test_stale_lock_file_contents_do_not_claim_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    lock_path = tmp_path / "backend_instance.lock"
    lock_path.write_text(f"{2**22}\n0\n", encoding="utf-8")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    lease = acquire_backend_instance_lease()
    try:
        assert lock_path.exists()
        if os.name == "posix":
            assert lock_path.stat().st_mode & 0o777 == 0o600
    finally:
        lease.release()


@pytest.mark.unit
def test_released_backend_lease_allows_a_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    first = acquire_backend_instance_lease()
    first.release()

    successor = acquire_backend_instance_lease()
    successor.release()


@pytest.mark.unit
def test_pid_bound_lease_refuses_release_from_an_inheriting_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.backend_instance as backend_instance

    releases: list[str] = []
    raw_lease = SimpleNamespace(release=lambda: releases.append("raw-release"))
    lease = backend_instance.BackendInstanceLease(raw_lease, owner_pid=101)
    monkeypatch.setattr(backend_instance.os, "getpid", lambda: 202)

    with pytest.raises(RuntimeError, match="inherited backend lease"):
        lease.release()

    assert releases == []


@pytest.mark.unit
@pytest.mark.skipif(os.name != "posix", reason="requires POSIX descriptor ownership")
def test_posix_lease_retains_descriptor_until_unlock_and_close_both_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.backend_instance as backend_instance

    events: list[str] = []
    unlock_attempts = 0
    close_attempts = 0

    def unlock(descriptor: int, operation: int) -> None:
        nonlocal unlock_attempts
        assert descriptor == 42
        assert operation == backend_instance.fcntl.LOCK_UN
        unlock_attempts += 1
        events.append(f"unlock-{unlock_attempts}")
        if unlock_attempts == 1:
            raise OSError("unlock unavailable")

    def close(descriptor: int) -> None:
        nonlocal close_attempts
        assert descriptor == 42
        close_attempts += 1
        events.append(f"close-{close_attempts}")
        if close_attempts == 1:
            raise OSError("close unavailable")

    monkeypatch.setattr(backend_instance.fcntl, "flock", unlock)
    monkeypatch.setattr(backend_instance.os, "close", close)
    raw_lease = backend_instance._PosixBackendFileLease(42)

    with pytest.raises(OSError, match="unlock unavailable"):
        raw_lease.release()
    assert raw_lease._descriptor == 42

    with pytest.raises(OSError, match="close unavailable"):
        raw_lease.release()
    assert raw_lease._descriptor == 42

    raw_lease.release()

    assert raw_lease._descriptor is None
    assert events == ["unlock-1", "unlock-2", "close-1", "unlock-3", "close-2"]


@pytest.mark.unit
def test_failed_retained_release_keeps_global_retry_authority() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise RuntimeError("unlock and close incomplete")

    lease = RetryingLease()
    backend_instance.retain_backend_instance_lease(lease)
    try:
        with pytest.raises(RuntimeError, match="unlock and close incomplete"):
            backend_instance.release_retained_backend_instance_lease(lease)

        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        backend_instance.release_retained_backend_instance_lease(lease)

        assert lease.release_calls == 2
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
def test_failed_release_keeps_descriptor_wrapper_and_recovery_owner_attached() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingRawLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise OSError("descriptor close incomplete")

    raw_lease = RetryingRawLease()
    lease = backend_instance.BackendInstanceLease(raw_lease)
    recovery_owner = object()
    lease.retain_recovery_owner(recovery_owner)
    backend_instance.retain_backend_instance_lease(lease)
    try:
        with pytest.raises(OSError, match="descriptor close incomplete"):
            backend_instance.release_retained_backend_instance_lease(lease)

        assert lease._released is False
        assert lease.recovery_owner is recovery_owner
        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        backend_instance.release_retained_backend_instance_lease(lease)

        assert lease._released is True
        assert lease.recovery_owner is None
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
def test_direct_release_failure_self_retains_global_authority_until_retry() -> None:
    import flinttrade_core.backend_instance as backend_instance

    class RetryingRawLease:
        def __init__(self) -> None:
            self.release_calls = 0

        def release(self) -> None:
            self.release_calls += 1
            if self.release_calls == 1:
                raise OSError("direct descriptor release incomplete")

    raw_lease = RetryingRawLease()
    lease = backend_instance.BackendInstanceLease(raw_lease)
    try:
        with pytest.raises(OSError, match="direct descriptor release incomplete"):
            lease.release()

        assert lease._released is False
        assert any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)

        lease.release()

        assert lease._released is True
        assert not any(retained is lease for retained in backend_instance._RETAINED_FAILED_LEASES)
    finally:
        with backend_instance._RETAINED_FAILED_LEASES_LOCK:
            backend_instance._RETAINED_FAILED_LEASES[:] = [
                retained
                for retained in backend_instance._RETAINED_FAILED_LEASES
                if retained is not lease
            ]


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_forked_child_destructor_cannot_release_parent_backend_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    entered = tmp_path / "fork-entered"
    release = tmp_path / "fork-release"
    env = os.environ.copy()
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _FORKED_CHILD_DESTRUCTOR_HOLDER,
            str(tmp_path),
            str(entered),
            str(release),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_marker(entered, process)
        contender = subprocess.run(
            [sys.executable, "-c", _TRY_BACKEND_LEASE, str(tmp_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        assert contender.returncode == 23, contender.stdout + contender.stderr
    finally:
        release.touch(exist_ok=True)
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5.0)

    stdout, stderr = process.communicate()
    assert process.returncode == 0, stdout + stderr
    successor = subprocess.run(
        [sys.executable, "-c", _TRY_BACKEND_LEASE, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5.0,
        check=False,
    )
    assert successor.returncode == 0, successor.stdout + successor.stderr


@pytest.mark.unit
def test_different_workspaces_can_hold_independent_backend_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(first_workspace))
    first = acquire_backend_instance_lease()
    try:
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(second_workspace))
        second = acquire_backend_instance_lease()
        second.release()
    finally:
        first.release()


class _FakeLease:
    def __init__(self, events: list[str], proof: object) -> None:
        self._events = events
        self.proof = proof

    def release(self) -> None:
        self._events.append("release")


@pytest.mark.unit
def test_standalone_run_claims_before_start_and_releases_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_proof,
) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    runtime._initialise_runtime = lambda: None
    runtime._shutdown_task = None
    runtime._shutdown_request_task = None

    async def fail_start(_self: object) -> None:
        events.append("start")
        raise RuntimeError("startup failed")

    runtime.start = MethodType(fail_start, runtime)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events, backend_lease_proof),
    )

    with pytest.raises(RuntimeError, match="startup failed"):
        runtime.run()

    assert events == ["acquire", "start", "release"]


@pytest.mark.unit
def test_standalone_run_retains_lease_when_live_owner_teardown_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_proof,
) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    runtime._initialise_runtime = lambda: None
    runtime._flask_app = Flask("failed-runtime-owner")
    runtime._stop_completed = False

    def fail_run(_self: object) -> None:
        events.append("run")
        raise RuntimeError("shutdown encountered errors")

    runtime._run_owned = MethodType(fail_run, runtime)
    lease = _FakeLease(events, backend_lease_proof)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        app_module,
        "retain_backend_instance_lease",
        lambda retained: events.append("retain") if retained is lease else None,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="shutdown encountered errors"):
        runtime.run()

    assert events == ["acquire", "run", "retain"]


@pytest.mark.unit
def test_standalone_contention_prevents_start(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning

    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    started = False

    async def start(_self: object) -> None:
        nonlocal started
        started = True

    runtime.start = MethodType(start, runtime)

    def reject() -> Any:
        raise BackendInstanceAlreadyRunning("already running")

    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", reject)

    with pytest.raises(BackendInstanceAlreadyRunning, match="already running"):
        runtime.run()

    assert started is False


@pytest.mark.unit
def test_wsgi_retains_one_lease_for_the_cached_app(monkeypatch: pytest.MonkeyPatch, backend_lease_proof) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    flask_app = Flask("wsgi-backend-lease")
    lease = _FakeLease(events, backend_lease_proof)
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        app_module,
        "create_flask_app",
        lambda **kwargs: events.append("factory") or flask_app,
    )

    assert app_module._get_wsgi_app(shutdown_callback=lambda: None) is flask_app
    assert app_module._get_wsgi_app(shutdown_callback=lambda: None) is flask_app
    assert app_module._stop_backend_lease_watch(flask_app, timeout=1)
    assert app_module._WSGI_BACKEND_LEASE is lease
    assert events == ["acquire", "factory"]


@pytest.mark.unit
def test_wsgi_rejects_an_app_cache_inherited_across_fork(monkeypatch: pytest.MonkeyPatch, backend_lease_proof) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    flask_app = Flask("inherited-wsgi-app")
    lease = _FakeLease(events, backend_lease_proof)
    monkeypatch.setattr(app_module, "_APP_CACHE", flask_app)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", 101, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", lease)
    monkeypatch.setattr(app_module.os, "getpid", lambda: 202)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )

    with pytest.raises(RuntimeError, match="inherited WSGI app"):
        app_module._get_wsgi_app()

    assert events == []


@pytest.mark.unit
@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_preloaded_wsgi_callable_rejects_a_real_forked_request(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _FORKED_PRELOADED_WSGI_REQUEST, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_wsgi_releases_lease_when_factory_fails(monkeypatch: pytest.MonkeyPatch, backend_lease_proof) -> None:
    import flinttrade_core.app as app_module

    events: list[str] = []
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None, raising=False)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(
        app_module,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events, backend_lease_proof),
    )

    def fail_factory(**kwargs) -> Flask:
        events.append("factory")
        raise RuntimeError("factory failed")

    monkeypatch.setattr(app_module, "create_flask_app", fail_factory)

    with pytest.raises(RuntimeError, match="factory failed"):
        app_module._get_wsgi_app()

    assert app_module._APP_CACHE is None
    assert app_module._WSGI_BACKEND_LEASE is None
    assert events == ["acquire", "factory", "release"]


@pytest.mark.unit
def test_desktop_serve_holds_lease_until_server_and_cleanup_finish(
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_proof,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    flask_app = Flask("desktop-backend-lease")
    flask_app.config["AUDIT"] = SimpleNamespace(close=lambda: events.append("cleanup"))
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events, backend_lease_proof),
    )
    monkeypatch.setattr(desktop, "_build_app", lambda proof: events.append("build") or flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_port=5100,
            run=lambda: events.append("serve"),
        ),
    )

    desktop.serve(5100, ready_writer=lambda _message: None)

    assert events == ["acquire", "build", "serve", "cleanup", "release"]


@pytest.mark.unit
def test_desktop_serve_releases_lease_when_app_build_fails(
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_proof,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or _FakeLease(events, backend_lease_proof),
    )

    def fail_build(proof) -> Flask:
        events.append("build")
        raise RuntimeError("build failed")

    monkeypatch.setattr(desktop, "_build_app", fail_build)

    with pytest.raises(RuntimeError, match="build failed"):
        desktop.serve(5100)

    assert events == ["acquire", "build", "release"]


@pytest.mark.unit
def test_desktop_serve_retains_lease_when_shutdown_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    backend_lease_proof,
) -> None:
    import flinttrade_core.desktop as desktop

    events: list[str] = []
    lease = _FakeLease(events, backend_lease_proof)
    monkeypatch.setattr(
        desktop,
        "acquire_backend_instance_lease",
        lambda: events.append("acquire") or lease,
    )
    monkeypatch.setattr(
        desktop,
        "retain_backend_instance_lease",
        lambda retained: events.append("retain") if retained is lease else None,
        raising=False,
    )

    def fail_shutdown(*_args: object, **_kwargs: object) -> None:
        events.append("serve")
        raise desktop.DesktopBackendShutdownIncomplete("shutdown failed")

    monkeypatch.setattr(desktop, "_serve_owned", fail_shutdown)

    with pytest.raises(RuntimeError, match="shutdown failed"):
        desktop.serve(5100)

    assert events == ["acquire", "serve", "retain"]
