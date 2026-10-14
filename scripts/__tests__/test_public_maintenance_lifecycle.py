"""Real public CLI/uninstaller ownership regressions; owned disposable I/O only."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.integration


def copy_cli(root: Path) -> Path:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for source in (REPO / "scripts").glob("*.py"):
        shutil.copy2(source, scripts / source.name)
    package = root / "packages/core/core/src/flinttrade_core"
    package.mkdir(parents=True)
    real_core = REPO / "packages/core/core/src/flinttrade_core"
    (package / "__init__.py").write_text(f"__path__.append({str(real_core)!r})\n")
    for name in ("cli.py", "app.py"):
        (package / name).write_text("raise SystemExit(42)  # inert external backend/provisioner\n")
    return scripts / "ft.py"


def base_env(root: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir()
    return {**os.environ, "HOME": str(home), "FLINTTRADE_HOME": str(home / ".flinttrade"),
            "FLINTTRADE_WORKSPACE_DIR": str(home / ".flinttrade")}


def stop_fixture(child: subprocess.Popen[str]) -> None:
    if child.poll() is None:
        child.terminate()
    try:
        child.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=5)


@pytest.mark.parametrize("command", ["stop", "restart"])
def test_public_cli_never_terminates_unrelated_listener(tmp_path, command):
    cli = copy_cli(tmp_path)
    env = base_env(tmp_path)
    listener = subprocess.Popen(
        [sys.executable, "-u", "-c", """
import socket, time
s=socket.socket(); s.bind(('127.0.0.1',0)); s.listen()
print(s.getsockname()[1], flush=True)
time.sleep(60)
"""], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], text=True)
    try:
        assert listener.stdout is not None
        port = int(listener.stdout.readline())
        env["FLINTTRADE_BACKEND_PORT"] = str(port)
        shims = tmp_path / "bin"
        shims.mkdir()
        lsof = shims / "lsof"
        lsof.write_text(f"#!/bin/sh\nprintf '%s\\n' {listener.pid}\n")
        lsof.chmod(0o700)
        env["PATH"] = f"{shims}{os.pathsep}{env['PATH']}"
        result = subprocess.run([sys.executable, str(cli), command], env=env, capture_output=True,
                                text=True, timeout=20, check=False)
        assert listener.poll() is None, f"public {command} killed unrelated port owner: {result.stdout}"
        assert sentinel.poll() is None
        assert result.returncode != 0, result.stdout + result.stderr
        assert "refus" in (result.stdout + result.stderr).lower()
    finally:
        stop_fixture(listener)
        stop_fixture(sentinel)


def test_external_purge_retains_live_independent_workspace(tmp_path):
    env = base_env(tmp_path)
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    workspace.mkdir()
    payload = workspace / "journal.sqlite"
    payload.write_bytes(b"synthetic journal bytes")
    script = tmp_path / "uninstall.sh"
    shutil.copy2(REPO / "scripts/install/flinttrade-uninstall.sh", script)
    owner = subprocess.Popen([sys.executable, "-u", "-c", """
import time
from flinttrade_core.backend_instance import acquire_backend_instance_lease
lease = acquire_backend_instance_lease()
print('OWNED', flush=True)
try: time.sleep(60)
finally: lease.release()
"""], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert owner.stdout is not None
        assert owner.stdout.readline().strip() == "OWNED"
        result = subprocess.run(["bash", str(script), "--purge", "--yes"], env=env, text=True,
                                capture_output=True, timeout=20, check=False)
        assert payload.exists(), f"public purge deleted a live owner's data: {result.stdout}"
        assert payload.read_bytes() == b"synthetic journal bytes"
        assert owner.poll() is None
        assert result.returncode != 0
        assert "retained" in result.stdout.lower() or "kept" in result.stdout.lower()
    finally:
        stop_fixture(owner)


@pytest.mark.parametrize("flags,ambient", [(["--purge", "--yes"], False), ([], True)])
def test_purge_needs_explicit_invocation_and_verified_protection_policy(tmp_path, flags, ambient):
    env = base_env(tmp_path)
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    workspace.mkdir()
    payload = workspace / "journal.sqlite"
    payload.write_bytes(b"retain even when no backend is running")
    if ambient:
        env.update(FLINTTRADE_UNINSTALL_PURGE="1", FLINTTRADE_UNINSTALL_YES="1")
    script = tmp_path / "uninstall.sh"
    shutil.copy2(REPO / "scripts/install/flinttrade-uninstall.sh", script)
    result = subprocess.run(["bash", str(script), *flags], env=env, text=True,
                            capture_output=True, timeout=20, check=False)
    assert payload.exists(), result.stdout + result.stderr
    assert payload.read_bytes() == b"retain even when no backend is running"
    if not ambient:
        assert result.returncode != 0
        assert "policy" in (result.stdout + result.stderr).lower()


def test_public_start_does_not_provision_during_shared_maintenance(tmp_path):
    cli = copy_cli(tmp_path)
    env = base_env(tmp_path)
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    workspace.mkdir()
    marker = tmp_path / "provisioned"
    (tmp_path / "packages/core/core/src/flinttrade_core/cli.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit(42)\n"
    )
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance

    with acquire_workspace_maintenance(workspace):
        result = subprocess.run([sys.executable, str(cli), "start"], env=env, text=True,
                                capture_output=True, timeout=20, check=False)
    assert not marker.exists(), "public start provisioned inside the active maintenance transaction"
    assert result.returncode != 0


def test_start_during_removed_workspace_purge_cannot_recreate_it(tmp_path):
    cli = copy_cli(tmp_path)
    env = base_env(tmp_path)
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    workspace.mkdir()
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance

    with acquire_workspace_maintenance(workspace):
        shutil.rmtree(workspace)
        result = subprocess.run([sys.executable, str(cli), "start"], env=env, text=True,
                                capture_output=True, timeout=20, check=False)
        assert result.returncode != 0
        assert not workspace.exists(), "provisioning recreated a workspace inside active purge exclusion"
        backend = subprocess.run([sys.executable, "-c", "from flinttrade_core.backend_instance import "
                                  "acquire_backend_instance_lease; acquire_backend_instance_lease()"],
                                 env=env, text=True, capture_output=True, timeout=10)
        assert backend.returncode != 0
        assert not workspace.exists(), "normal backend recreated a workspace inside active purge exclusion"
