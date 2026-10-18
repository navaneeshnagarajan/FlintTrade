"""Actual copied public CLI against a real local maintenance owner channel."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]

OWNER_SOURCE = """
import importlib.util, json, os, sys, threading
from pathlib import Path
from flask import Flask
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.installation_state import InstallationState
from flinttrade_core.app import _install_runtime_request_tracking
from flinttrade_core.execution_sessions import ExecutionSessions
from flinttrade_core.protection_grants import install_protection_services
if importlib.util.find_spec("flinttrade_core.maintenance_control") is None:
    print("MISSING_MAINTENANCE_CONTROL", flush=True)
    raise SystemExit(44)
from flinttrade_core.maintenance_control import install_maintenance_control
from flinttrade_core.workspace import Workspace
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_ai.run_store import AgentRunStore
from flinttrade_engine.scheduler import StrategyScheduler
from flinttrade_gateway.registry import BrokerRegistry
workspace = Path(os.environ['FLINTTRADE_WORKSPACE_DIR'])
workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
lease = acquire_backend_instance_lease()
app = Flask(__name__)
app.config['BACKEND_LEASE_PROOF'] = lease.proof
_install_runtime_request_tracking(app)
Workspace(workspace).initialise()
manual = SandboxEngine(str(workspace / 'sandbox/state.sqlite'), strict_existing=os.environ.get('R21_SCENARIO') == 'idle')
legacy_path = workspace / ('alternate-legacy.sqlite' if os.environ.get('R21_UNSAFE') == 'alternate-legacy' else 'practice_agent_runs.sqlite')
legacy = AgentRunStore(legacy_path, strict_existing=os.environ.get('R21_SCENARIO') == 'idle' and os.environ.get('R21_UNSAFE') != 'alternate-legacy')
app.config.update(DATA_SANDBOX_ENGINE=manual, PRACTICE_AGENT_RUN_STORE=legacy,
                  SCHEDULER=StrategyScheduler(), REGISTRY=BrokerRegistry())
installation = InstallationState()
sessions = ExecutionSessions(app, workspace / ('other-sessions' if os.environ.get('R21_UNSAFE') == 'alternate-registry' else 'execution-sessions'))
app.config['EXECUTION_SESSIONS'] = sessions
protection = install_protection_services(app, workspace)
unsafe = os.environ.get('R21_UNSAFE')
if unsafe == 'protection':
    with protection._db().transaction() as db:
        db.execute('INSERT INTO grants VALUES (?,?,?)', ('retained-duty', 1, json.dumps({
            'scope': {'run_id':'retained-duty','actor':'synthetic-owner','account':'paper:sandbox','environment':'paper'},
            'revoked':True, 'settled':False, 'policy':{'valid_until':0}})))
if unsafe == 'handover':
    from flinttrade_core.execution_session import ExecutionSession
    scope = ExecutionSession('paper-a','synthetic-owner','paper:run:paper-a','paper')
    sessions.create(scope, kind='practice', config={})
    with sessions.db.transaction() as db:
        db.execute("UPDATE sessions SET state='handover' WHERE run_id='paper-a'")
if unsafe == 'lost-history':
    (workspace / 'practice_agent_runs.sqlite').rename(workspace / 'retained-history.sqlite')
if unsafe == 'approval':
    app.config['SAFE_MAINTENANCE_POLICY'] = lambda: True
    (workspace / 'approval.json').write_text(json.dumps({'registry_complete':True,'disposal_authorised':True}))
stopped = threading.Event()
if os.environ.get('R21_HOLD_REQUEST'):
    held_request = app.config['RUNTIME_REQUEST_TRACKER'].try_admit()
control = install_maintenance_control(app, workspace, request_shutdown=stopped.set)
print('OWNER_READY', flush=True)
try:
    if stopped.wait(20):
        # This fixture owns exactly these actual runtimes. The production
        # caller instead invokes its existing full managed stop machinery.
        if os.environ.get('R21_HOLD_STOP'):
            threading.Event().wait(20)
        sessions.close()
        protection.close()
        manual.close()
        legacy.close()
        control.runtime_stopped(timeout=5)
finally:
    control.close()
    lease.release()
"""


def checkout(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "checkout"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for source in (REPO / "scripts").glob("*.py"):
        shutil.copy2(source, scripts / source.name)
    package = root / "packages/core/core/src/flinttrade_core"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"__path__.append({str(REPO / 'packages/core/core/src/flinttrade_core')!r})\n"
    )
    # Only external backend and provisioner are inert; maintenance is real.
    (package / "app.py").write_text("raise SystemExit(42)\n")
    (package / "cli.py").write_text("raise SystemExit(0)\n")
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    env = {**os.environ, "HOME": str(home), "FLINTTRADE_WORKSPACE_DIR": str(home / ".flinttrade")}
    env.pop("FLINTTRADE_INSTALLATION_STATE_DIR", None)
    return scripts / "ft.py", env


def provision(tmp_path: Path, env: dict[str, str]) -> None:
    result = subprocess.run([sys.executable, str(tmp_path / "checkout/scripts/ft.py"), "start"],
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 42, result.stdout + result.stderr
    assert (Path(env["HOME"]) / ".flinttrade-installation/maintenance-history.sqlite").exists()


def owner(tmp_path: Path, env: dict[str, str]) -> subprocess.Popen:
    if env.get("R21_SCENARIO") == "idle" and not (Path(env["HOME"]) / ".flinttrade-installation").exists():
        provision(tmp_path, env)
    script = tmp_path / "owner.py"
    script.write_text(OWNER_SOURCE)
    process = subprocess.Popen([sys.executable, "-u", str(script)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert process.stdout is not None
    line = process.stdout.readline().strip()
    if line != "OWNER_READY":
        process.wait(timeout=5)
        assert line == "OWNER_READY", line + process.stderr.read()
    return process


def run_purge_fault(tmp_path: Path, fault: str) -> tuple[subprocess.CompletedProcess, Path, dict]:
    """Run the copied uninstaller/real helper with only filesystem I/O faulted."""
    import json

    _cli, env = checkout(tmp_path)
    env["R21_SCENARIO"] = "idle"
    home = Path(env["HOME"])
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    provision(tmp_path, env)
    payload = workspace / "keep.bin"
    payload.write_bytes(b"fault-test-execution-history")
    race_code = (
        "import os, fcntl\nfrom pathlib import Path\n"
        "workspace=Path(os.environ['FLINTTRADE_WORKSPACE_DIR'])\n"
        "fd=os.open(workspace.parent/('.'+workspace.name+'.backend-instance.lock'), os.O_RDWR)\n"
        "try:\n    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
        "except BlockingIOError:\n    pass\n"
        "else:\n    raise SystemExit('kernel exclusion was not continuously held')\n"
        "finally:\n    os.close(fd)\n"
        "from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance, WorkspaceMaintenanceUnavailable\n"
        "try:\n    with acquire_workspace_maintenance(Path(os.environ['FLINTTRADE_WORKSPACE_DIR'])): pass\n"
        "except WorkspaceMaintenanceUnavailable:\n    raise SystemExit(37)\n"
    )
    driver = tmp_path / "fault-driver.py"
    driver.write_text(
        "import os, runpy, sys, subprocess\nfrom pathlib import Path\n"
        "import flinttrade_core.maintenance_purge as purge\n"
        f"fault={fault!r}\nworkspace=Path({str(workspace)!r})\n"
        "original=purge._remove\noriginal_rename=purge._rename\n"
        f"race_code={race_code!r}\n"
        "def rename(parent,name,destination,target):\n"
        "    if name == workspace.name:\n"
        "        raced=subprocess.run([sys.executable,'-c',race_code],capture_output=True)\n"
        "        assert raced.returncode == 37, raced.stderr\n"
        "        if fault == 'swap':\n"
        "            workspace.rename(workspace.parent/'rescued')\n"
        "            unrelated=workspace.parent/'unrelated'; unrelated.mkdir(); (unrelated/'keep').write_bytes(b'unrelated')\n"
        "            workspace.symlink_to(unrelated, target_is_directory=True)\n"
        "        if fault == 'lockswap':\n"
        "            stable=workspace.parent/('..flinttrade.backend-instance.lock')\n"
        "            stable.rename(workspace.parent/'retained-lock'); stable.touch(mode=0o600)\n"
        "    return original_rename(parent,name,destination,target)\n"
        "purge._rename=rename\n"
        "def remove(parent,name,expected,prefix='',*,guard=None):\n"
        "    if not prefix:\n"
        "        if fault == 'fail': raise OSError('synthetic unlink failure')\n"
        "        if fault == 'noop': return\n"
        "    original(parent,name,expected,prefix,guard=guard)\n"
        "    if not prefix and fault == 'recreate':\n"
        "        workspace.mkdir(exist_ok=True); (workspace/'recreated').write_bytes(b'concurrent data')\n"
        "purge._remove=remove\n"
        "sys.argv=['flinttrade_core.workspace_maintenance',*sys.argv[3:]]\n"
        "runpy.run_module('flinttrade_core.workspace_maintenance',run_name='__main__')\n"
    )
    interpreter = workspace / "src/FlintTrade/.venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{driver}" "$@"\n')
    interpreter.chmod(0o700)
    process = owner(tmp_path, env)
    script = tmp_path / "uninstall.sh"
    shutil.copy2(REPO / "scripts/install/flinttrade-uninstall.sh", script)
    try:
        result = subprocess.run(["bash", str(script), "--purge", "--yes"], env=env,
                                capture_output=True, text=True, timeout=20)
        receipts = [json.loads(path.read_text()) for path in (home / "..flinttrade.maintenance").glob("purge-*.json")]
        failed = [record for record in receipts if record["phase"] == "retry_required"]
        assert len(failed) == 1, result.stdout + result.stderr
        return result, home, failed[0]
    finally:
        retire(process)


def retire(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)


def test_public_stop_refuses_incomplete_real_historical_census(tmp_path):
    cli, env = checkout(tmp_path)
    process = owner(tmp_path, env)
    try:
        result = subprocess.run([sys.executable, str(cli), "stop"], env=env, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode != 0
        assert "execution census incomplete" in result.stdout + result.stderr
        assert process.poll() is None
    finally:
        retire(process)


def test_existing_ownership_inode_cannot_mint_fresh_history_provenance(tmp_path):
    cli, env = checkout(tmp_path)
    home = Path(env["HOME"])
    stable = home / "..flinttrade.backend-instance.lock"
    stable.write_bytes(b"earlier installation custody")
    stable.chmod(0o600)
    result = subprocess.run([sys.executable, str(cli), "start"], env=env, capture_output=True,
                            text=True, timeout=15)
    assert result.returncode == 42, result.stdout + result.stderr
    assert stable.read_bytes() == b"earlier installation custody"
    assert not (home / ".flinttrade-installation/maintenance-history.sqlite").exists(), \
        "missing historical lineage was silently reclassified as a fresh safe installation"


def test_public_idle_stop_waits_for_real_owner_exit(tmp_path):
    cli, env = checkout(tmp_path)
    env["R21_SCENARIO"] = "idle"
    process = owner(tmp_path, env)
    try:
        result = subprocess.run([sys.executable, str(cli), "stop"], env=env, capture_output=True,
                                text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
        assert process.wait(timeout=1) == 0
        assert "stopped" in result.stdout.lower()
        assert (Path(env["FLINTTRADE_WORKSPACE_DIR"]) / "execution-sessions/registry.sqlite").exists()
    finally:
        retire(process)


def test_external_idle_purge_executes_the_real_helper_transaction(tmp_path):
    _cli, env = checkout(tmp_path)
    env["R21_SCENARIO"] = "idle"
    home = Path(env["HOME"])
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    interpreter = workspace / "src/FlintTrade/.venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    workspace.chmod(0o700)
    interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    interpreter.chmod(0o700)
    provision(tmp_path, env)
    payload = workspace / "journal.sqlite"
    payload.write_bytes(b"explicit synthetic purge")
    profile = home / ".config/flinttrade-shell"
    profile.mkdir(parents=True)
    (profile / "settings").write_bytes(b"synthetic profile")
    process = owner(tmp_path, env)
    script = tmp_path / "uninstall.sh"
    shutil.copy2(REPO / "scripts/install/flinttrade-uninstall.sh", script)
    try:
        result = subprocess.run(["bash", str(script), "--purge", "--yes"], env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert process.wait(timeout=1) == 0
        assert not workspace.exists()
        assert not profile.exists()
        assert not (home / ".flinttrade-installation").exists()
        assert (home / "..flinttrade.backend-instance.lock").is_file()
        assert "purge complete" in result.stdout.lower()
    finally:
        retire(process)


def test_public_restart_starts_only_after_exact_exit_without_rearming(tmp_path):
    import sqlite3

    cli, env = checkout(tmp_path)
    env["R21_SCENARIO"] = "idle"
    process = owner(tmp_path, env)
    marker = tmp_path / "successor-started"
    app = tmp_path / "checkout/packages/core/core/src/flinttrade_core/app.py"
    app.write_text(
        "from pathlib import Path\n"
        "from flinttrade_core.backend_instance import acquire_backend_instance_lease\n"
        "lease=acquire_backend_instance_lease()\n"
        f"Path({str(marker)!r}).write_text('normal-backend-lease-acquired')\n"
        "lease.release()\n"
    )
    try:
        result = subprocess.run([sys.executable, str(cli), "restart"], env=env, capture_output=True,
                                text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        assert process.wait(timeout=1) == 0
        assert marker.read_text() == "normal-backend-lease-acquired"
        workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
        with sqlite3.connect(workspace / "execution-sessions/registry.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM sessions WHERE entries=1").fetchone() == (0,)
    finally:
        retire(process)


@pytest.mark.parametrize("surface", ["stop", "external-purge"])
@pytest.mark.parametrize("unsafe", ["protection", "handover", "lost-history", "approval", "alternate-registry", "alternate-legacy"])
def test_public_unknown_or_protected_stop_preserves_owner_and_bytes(tmp_path, unsafe, surface):
    cli, env = checkout(tmp_path)
    if unsafe != "approval":
        env["R21_SCENARIO"] = "idle"
    env["R21_UNSAFE"] = unsafe
    process = owner(tmp_path, env)
    workspace = Path(env["FLINTTRADE_WORKSPACE_DIR"])
    retained = workspace / "journal.bin"
    retained.write_bytes(b"non-layout execution history")
    command = [sys.executable, str(cli), "stop"]
    if surface == "external-purge":
        interpreter = workspace / "src/FlintTrade/.venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        interpreter.chmod(0o700)
        script = tmp_path / "uninstall.sh"
        shutil.copy2(REPO / "scripts/install/flinttrade-uninstall.sh", script)
        command = ["bash", str(script), "--purge", "--yes"]
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0
        assert "refused" in result.stdout.lower()
        assert process.poll() is None
        assert retained.read_bytes() == b"non-layout execution history"
        if unsafe == "protection":
            assert "protection duties" in result.stdout
    finally:
        retire(process)


@pytest.mark.parametrize("command", ["stop", "restart"])
@pytest.mark.parametrize("held", ["R21_HOLD_STOP", "R21_HOLD_REQUEST"])
def test_public_stop_timeout_keeps_pending_custody_and_does_not_restart(tmp_path, command, held):
    import json

    cli, env = checkout(tmp_path)
    env.update(R21_SCENARIO="idle")
    env[held] = "1"
    process = owner(tmp_path, env)
    try:
        try:
            result = subprocess.run([sys.executable, str(cli), command, "--timeout", "0.2"], env=env,
                                    capture_output=True, text=True, timeout=3)
        except subprocess.TimeoutExpired:
            pytest.fail("public stop ignored its bounded maintenance timeout")
        assert result.returncode != 0
        assert process.poll() is None
        pending = Path(env["HOME"]) / "..flinttrade.maintenance/pending.json"
        assert json.loads(pending.read_text())["phase"] == "retry_required"
        assert "stopped:" not in result.stdout.lower()
    finally:
        retire(process)


@pytest.mark.parametrize("fault", ["swap", "lockswap"])
def test_public_purge_swap_refuses_and_retains_bytes_and_lineage(tmp_path, fault):
    result, home, receipt = run_purge_fault(tmp_path, fault)
    assert result.returncode != 0
    assert "purge complete" not in result.stdout.lower()
    assert (home / ".flinttrade-installation/installation_id").exists()
    if fault == "swap":
        assert (home / "rescued/keep.bin").read_bytes() == b"fault-test-execution-history"
        assert (home / "unrelated/keep").read_bytes() == b"unrelated"
    else:
        pending = home / "..flinttrade.maintenance" / receipt["pending"]["member"]
        assert (pending / "keep.bin").read_bytes() == b"fault-test-execution-history"


@pytest.mark.parametrize("field", ["installation", "generation", "pid"])
def test_public_stale_owner_identity_never_controls_a_successor(tmp_path, field):
    import json
    from uuid import uuid4

    cli, env = checkout(tmp_path)
    env["R21_SCENARIO"] = "idle"
    process = owner(tmp_path, env)
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    discovery = Path(env["HOME"]) / "..flinttrade.maintenance/owner.json"
    value = json.loads(discovery.read_text())
    value[field] = sentinel.pid if field == "pid" else str(uuid4())
    discovery.write_text(json.dumps(value))
    try:
        result = subprocess.run([sys.executable, str(cli), "stop"], env=env, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode != 0
        assert "refused" in result.stdout.lower()
        assert process.poll() is None
        assert sentinel.poll() is None
        assert not discovery.with_name("pending.json").exists()
    finally:
        retire(process)
        retire(sentinel)
