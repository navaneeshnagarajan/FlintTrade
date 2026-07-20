"""Tests for the desktop uninstall scripts.

The uninstallers must remove the full application-side footprint (launcher
files, Tauri/WebView residue keyed by ``com.flinttrade.app``, logs, source
clone) while keeping the FlintTrade workspace — credential vault, auth.db,
journals, workspace.json — unless ``--purge`` is explicitly confirmed. All
filesystem tests run against a throwaway ``HOME`` with ``pkill``/``lsof``
shimmed to no-ops, so a live desktop app or backend on the developer machine
is never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-uninstall.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-uninstall.ps1"

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"

BUNDLE_ID = "com.flinttrade.app"


def _fake_bin(tmp_path: Path, os_name: str) -> str:
    """Build a PATH whose ``uname`` reports ``os_name`` and whose process
    tools (``pkill``, ``lsof``) are no-ops, so the uninstaller under test can
    never stop a real FlintTrade app or backend on the developer machine."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text(f"#!/bin/sh\nprintf '%s\\n' {os_name!r}\n")
    uname.chmod(0o755)
    for tool in ("pkill", "lsof"):
        shim = bin_dir / tool
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin"


def _run(tmp_path: Path, *flags: str, os_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SH), *flags],
        cwd=ROOT,
        env={"PATH": _fake_bin(tmp_path, os_name), "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _plant_linux_footprint(home: Path) -> dict[str, Path]:
    paths = {
        "wrapper": home / ".local" / "bin" / "flinttrade",
        "appimage": home / ".local" / "bin" / "flinttrade.AppImage",
        "opt": home / ".local" / "opt" / "flinttrade" / "AppRun",
        "desktop_entry": home / ".local" / "share" / "applications" / "flinttrade.desktop",
        "icon": home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / "flinttrade.png",
        "state": home / ".local" / "state" / "flinttrade" / "desktop-launch.log",
        "webkit_share": home / ".local" / "share" / BUNDLE_ID / "storage",
        "webkit_cache": home / ".cache" / BUNDLE_ID / "cache",
        "webkit_config": home / ".config" / BUNDLE_ID / "prefs",
        "src_clone": home / ".flinttrade" / "src" / "FlintTrade" / "README.md",
        "workspace": home / ".flinttrade" / "workspace.json",
        "vault": home / ".flinttrade" / "credentials.db",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return paths


@pytest.mark.unit
def test_unix_uninstaller_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SH)], check=True, cwd=ROOT)


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_uninstaller_parses_when_powershell_is_available() -> None:
    subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            "$errs = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{PS1}', [ref]$null, [ref]$errs); "
            "if ($errs) { $errs | ForEach-Object { Write-Error $_.Message }; exit 1 }",
        ],
        check=True,
        cwd=ROOT,
    )


@pytest.mark.unit
def test_linux_uninstall_removes_residue_and_keeps_workspace(tmp_path: Path) -> None:
    paths = _plant_linux_footprint(tmp_path)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stderr
    for key in (
        "wrapper",
        "appimage",
        "opt",
        "desktop_entry",
        "icon",
        "state",
        "webkit_share",
        "webkit_cache",
        "webkit_config",
        "src_clone",
    ):
        assert not paths[key].exists(), f"{key} should have been removed: {paths[key]}"
    # The workspace — vault, journals, settings — survives a default uninstall.
    assert paths["workspace"].exists()
    assert paths["vault"].exists()
    assert "Workspace data kept" in result.stdout


@pytest.mark.unit
def test_linux_uninstall_purge_yes_deletes_workspace(tmp_path: Path) -> None:
    paths = _plant_linux_footprint(tmp_path)

    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 0, result.stderr
    assert not paths["workspace"].exists()
    assert not paths["vault"].exists()
    assert not (tmp_path / ".flinttrade").exists()


@pytest.mark.unit
def test_linux_uninstall_purge_without_consent_refuses_non_interactively(tmp_path: Path) -> None:
    paths = _plant_linux_footprint(tmp_path)

    result = _run(tmp_path, "--purge", os_name="Linux")

    assert result.returncode == 0, result.stderr
    # No TTY and no --yes: the purge must refuse rather than block or delete.
    assert paths["workspace"].exists()
    assert paths["vault"].exists()
    assert "workspace data kept" in result.stdout.lower()


@pytest.mark.unit
def test_macos_dry_run_lists_residue_and_deletes_nothing(tmp_path: Path) -> None:
    webkit = tmp_path / "Library" / "WebKit" / BUNDLE_ID / "storage"
    caches = tmp_path / "Library" / "Caches" / BUNDLE_ID / "cache"
    workspace = tmp_path / "Library" / "Application Support" / "flinttrade" / "workspace.json"
    for path in (webkit, caches, workspace):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")

    result = _run(tmp_path, "--dry-run", os_name="Darwin")

    assert result.returncode == 0, result.stderr
    assert webkit.exists()
    assert caches.exists()
    assert workspace.exists()
    assert f"Library/WebKit/{BUNDLE_ID}" in result.stdout
    assert f"Library/Caches/{BUNDLE_ID}" in result.stdout
    assert "nothing was deleted" in result.stdout.lower()


@pytest.mark.unit
def test_uninstall_reports_clean_when_nothing_is_installed(tmp_path: Path) -> None:
    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stderr
    assert "does not appear to be installed" in result.stdout
