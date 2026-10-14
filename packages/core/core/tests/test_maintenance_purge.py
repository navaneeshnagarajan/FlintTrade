"""Descriptor-bound filesystem phase; synthetic state and real exclusion only."""
from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.integration


def test_complete_purge_preserves_stable_lock_inode(tmp_path, monkeypatch):
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    workspace = home / ".flinttrade"
    workspace.mkdir(mode=0o700)
    profile = home / ".config/flinttrade-shell"
    profile.mkdir(parents=True)
    (workspace / "journal.sqlite").write_bytes(b"explicit synthetic journal")
    (profile / "settings").write_bytes(b"explicit synthetic profile")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("FLINTTRADE_INSTALLATION_STATE_DIR", raising=False)
    state = InstallationState()
    try:
        module = importlib.import_module("flinttrade_core.maintenance_purge")
    except ModuleNotFoundError:
        module = None
    assert module is not None, "purge has no held multi-target filesystem transaction"
    with acquire_workspace_maintenance(workspace):
        stable = home / "..flinttrade.backend-instance.lock"
        inode = stable.stat().st_ino
        plan = module.PurgePlan(workspace, state)
        assert workspace in plan.targets
        assert profile in plan.targets
        assert plan.targets[-1] == state.root
        plan.execute()
        assert not workspace.exists()
        assert not profile.exists()
        assert not state.root.exists()
        assert stable.stat().st_ino == inode
        assert plan.receipt()["phase"] == "complete"
        assert set(plan.receipt()["removed"]) == {str(path) for path in plan.roots}


def test_plan_refuses_replaced_parent_before_any_deletion(tmp_path, monkeypatch):
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.maintenance_purge import PurgePlan
    from flinttrade_core.maintenance_custody import MaintenanceRefused
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    workspace = home / ".flinttrade"
    workspace.mkdir(mode=0o700)
    (workspace / "keep").write_bytes(b"journal")
    profile = home / ".config/flinttrade-shell"
    profile.mkdir(parents=True)
    (profile / "keep").write_bytes(b"profile")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("FLINTTRADE_INSTALLATION_STATE_DIR", raising=False)
    installation = InstallationState()
    with acquire_workspace_maintenance(workspace):
        plan = PurgePlan(workspace, installation)
        # A new ordinary parent with the SAME moved target inode is a custody
        # change too; checking only target identities is not sufficient.
        config = home / ".config"
        config.rename(home / "old-config")
        config.mkdir()
        (home / "old-config/flinttrade-shell").rename(profile)
        with pytest.raises((MaintenanceRefused, OSError)):
            plan.execute()
        assert (workspace / "keep").read_bytes() == b"journal"
        assert (profile / "keep").read_bytes() == b"profile"
        assert installation.root.exists()


def test_purge_does_not_omit_unproven_installation_targets(tmp_path, monkeypatch):
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.maintenance_purge import PurgePlan
    from flinttrade_core.maintenance_custody import MaintenanceRefused

    home = tmp_path / "home"
    workspace = home / ".flinttrade"
    workspace.mkdir(mode=0o700, parents=True)
    launcher = home / ".local/bin/flinttrade-web"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"unproven executable")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("FLINTTRADE_INSTALLATION_STATE_DIR", raising=False)
    state = InstallationState()
    with pytest.raises(MaintenanceRefused):
        PurgePlan(workspace, state)
    assert launcher.read_bytes() == b"unproven executable"
    assert workspace.exists()
    assert state.root.exists()


def test_complete_plan_includes_proven_web_launcher_custom_source_and_receipt(tmp_path, monkeypatch):
    import hashlib
    from flinttrade_core.installation_state import InstallationState
    from flinttrade_core.maintenance_purge import PurgePlan
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance

    home = tmp_path / "home"
    workspace = home / ".flinttrade"
    workspace.mkdir(mode=0o700, parents=True)
    launcher = home / ".local/bin/flinttrade-web"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"#!/bin/sh\nexit 0\n")
    source = home / "custom-source"
    source.mkdir()
    for name in (".git", "pnpm-lock.yaml", "uv.lock", "pyproject.toml"):
        (source / name).touch()
    receipt_dir = home / ".local/state/flinttrade-web"
    receipt_dir.mkdir(mode=0o700, parents=True)
    receipt = receipt_dir / "web-install.receipt"
    receipt.write_text(f"format=flinttrade-web-install-v1\nplatform=Linux\nshim={launcher}\n"
                       f"shim_sha256={hashlib.sha256(launcher.read_bytes()).hexdigest()}\nshortcut=\n"
                       f"source={source}\ntools={workspace / 'tools'}\n")
    receipt.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("FLINTTRADE_INSTALLATION_STATE_DIR", raising=False)
    state = InstallationState()
    with acquire_workspace_maintenance(workspace):
        plan = PurgePlan(workspace, state)
        assert launcher in plan.targets and source in plan.targets and receipt_dir in plan.targets
        plan.execute()
        assert not launcher.exists() and not source.exists() and not receipt_dir.exists()
        assert plan.receipt()["phase"] == "complete"
