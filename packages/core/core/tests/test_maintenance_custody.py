"""Native ownership tests; all processes and paths are disposable fixtures."""
from __future__ import annotations

import importlib
import socket
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def test_peer_handle_observes_exact_owner_exit_without_pid_lookup(tmp_path):
    """A connected owner is pinned by the kernel, not a reusable PID snapshot."""
    try:
        custody = importlib.import_module("flinttrade_core.maintenance_custody")
    except ModuleNotFoundError:
        custody = None
    assert custody is not None, "maintenance lacks a retained native owner handle"
    endpoint = str(tmp_path / "owner.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(endpoint)
    listener.listen(1)
    child = subprocess.Popen([sys.executable, "-c", """
import socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
s.recv(1)
""", endpoint])
    try:
        listener.settimeout(5)
        with listener.accept()[0] as channel, custody.PeerProcessHandle(channel) as handle:
            assert handle.pid == child.pid
            assert not handle.wait_exited(0.01)
            channel.sendall(b"x")
            assert handle.wait_exited(5)
            assert child.wait(timeout=5) == 0
            # Reaping cannot retarget the retained pidfd to any successor.
            assert handle.wait_exited(0)
    finally:
        listener.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_maintenance_handoff_keeps_the_normal_kernel_exclusion(tmp_path, monkeypatch):
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease
    from flinttrade_core import maintenance_custody

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    lease = acquire_backend_instance_lease()
    try:
        transfer = getattr(maintenance_custody, "ExclusionTransfer", None)
        assert transfer is not None, "normal ownership has no continuous maintenance handoff"
        with transfer(lease.proof) as held:
            held.commit()
            lease.release()
            with pytest.raises(BackendInstanceAlreadyRunning):
                acquire_backend_instance_lease()
        successor = acquire_backend_instance_lease()
        successor.release()
    finally:
        lease.release()


def test_pending_handoff_refuses_new_backend_and_provisioning(tmp_path, monkeypatch):
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    custody = tmp_path / ".workspace.maintenance"
    custody.mkdir(mode=0o700)
    (custody / "pending.json").write_text('{"phase":"retry_required"}')
    with pytest.raises(BackendInstanceAlreadyRunning):
        acquired = acquire_backend_instance_lease()
        acquired.release()
    from flinttrade_core.workspace_maintenance import WorkspaceMaintenanceUnavailable, acquire_workspace_maintenance

    with pytest.raises(WorkspaceMaintenanceUnavailable):
        with acquire_workspace_maintenance(workspace):
            pytest.fail("migration may not bypass unfinished maintenance custody")
