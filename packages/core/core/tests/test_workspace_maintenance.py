"""Public maintenance exclusion against actual backend process ownership."""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def maintenance_module():
    spec = importlib.util.find_spec("flinttrade_core.workspace_maintenance")
    assert spec is not None, "public shared workspace maintenance owner is missing"
    return importlib.import_module(spec.name)


def contender(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", """
from flinttrade_core.backend_instance import acquire_backend_instance_lease, BackendInstanceAlreadyRunning
try:
    lease = acquire_backend_instance_lease()
except BackendInstanceAlreadyRunning:
    raise SystemExit(23)
lease.release()
"""],
        env={**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)},
        capture_output=True, text=True, timeout=10, check=False,
    )


def test_maintenance_excludes_real_backend_until_context_exit(tmp_path):
    module = maintenance_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with module.acquire_workspace_maintenance(workspace):
        result = contender(workspace)
        assert result.returncode == 23, result.stdout + result.stderr
    result = contender(workspace)
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_backend_excludes_maintenance(tmp_path, monkeypatch):
    module = maintenance_module()
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    lease = acquire_backend_instance_lease()
    try:
        with pytest.raises(module.WorkspaceMaintenanceUnavailable):
            with module.acquire_workspace_maintenance(tmp_path):
                pytest.fail("maintenance entered a live backend workspace")
    finally:
        lease.release()


def test_exclusion_survives_workspace_removal_and_recreation(tmp_path):
    module = maintenance_module()
    import shutil

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with module.acquire_workspace_maintenance(workspace):
        shutil.rmtree(workspace)
        workspace.mkdir()
        result = contender(workspace)
        assert result.returncode == 23, result.stdout + result.stderr
    result = contender(workspace)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "posix", reason="native legacy POSIX file-lock producer")
def test_legacy_backend_lock_excludes_maintenance(tmp_path):
    module = maintenance_module()
    import fcntl

    with (tmp_path / "backend_instance.lock").open("w") as legacy:
        fcntl.flock(legacy, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(module.WorkspaceMaintenanceUnavailable):
            with module.acquire_workspace_maintenance(tmp_path):
                pytest.fail("legacy backend owner was ignored")


def test_maintenance_never_mints_backend_authority(tmp_path):
    module = maintenance_module()
    from flinttrade_core.backend_instance import BackendLeaseUnavailable, require_backend_lease_proof

    with module.acquire_workspace_maintenance(tmp_path) as maintenance:
        with pytest.raises(BackendLeaseUnavailable):
            require_backend_lease_proof(maintenance)


@pytest.mark.skipif(os.name != "posix", reason="POSIX hard-link identity")
def test_ambiguous_hardlinked_lock_never_changes_unrelated_file(tmp_path):
    module = maintenance_module()
    target = tmp_path / "unrelated"
    target.write_bytes(b"keep exact bytes and mode")
    target.chmod(0o640)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    os.link(target, workspace / "backend_instance.lock")
    with pytest.raises(module.WorkspaceMaintenanceUnavailable):
        with module.acquire_workspace_maintenance(workspace):
            pytest.fail("hard-linked ownership inode was accepted")
    assert target.read_bytes() == b"keep exact bytes and mode"
    assert target.stat().st_mode & 0o777 == 0o640
