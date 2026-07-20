"""Tests for the desktop uninstall scripts.

The uninstallers must remove the disposable application footprint (launcher
files, caches, preferences, logs, source clone) while keeping BOTH kinds of
FlintTrade data unless ``--purge`` is explicitly confirmed: the workspace
(credential vault, auth.db, journals, workspace.json) and the WebView storage
whose localStorage is the only home of in-app saved content (trade journal
notes, flows, saved AI chats). All filesystem tests run against a throwaway
``HOME`` with ``pkill``/``lsof`` shimmed to no-ops, so a live desktop app or
backend on the developer machine is never touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-uninstall.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-uninstall.ps1"
TAURI_CONF = ROOT / "packages" / "apps" / "desktop" / "src-tauri" / "tauri.conf.json"
NSIS_HOOKS = ROOT / "packages" / "apps" / "desktop" / "src-tauri" / "windows" / "uninstall-hooks.nsh"

POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"

BUNDLE_ID = "com.flinttrade.app"


def _fake_bin(tmp_path: Path, os_name: str) -> str:
    """Build a PATH whose ``uname`` reports ``os_name`` and whose process
    tools (``pkill``, ``lsof``) are no-ops, so the uninstaller under test can
    never stop a real FlintTrade app or backend on the developer machine.
    ``defaults`` is shimmed too so the Darwin branch runs on any host."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text(f"#!/bin/sh\nprintf '%s\\n' {os_name!r}\n")
    uname.chmod(0o755)
    for tool in ("pkill", "lsof"):
        shim = bin_dir / tool
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
    defaults = bin_dir / "defaults"
    defaults.write_text("#!/bin/sh\nexit 0\n")
    defaults.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin"


def _run(
    tmp_path: Path, *flags: str, os_name: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": _fake_bin(tmp_path, os_name), "HOME": str(tmp_path)}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(SH), *flags],
        cwd=ROOT,
        env=env,
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
        "webview_storage": home / ".local" / "share" / BUNDLE_ID / "localstorage" / "notes",
        "webview_cache": home / ".cache" / BUNDLE_ID / "cache",
        "webview_config": home / ".config" / BUNDLE_ID / "prefs",
        "src_clone": home / ".flinttrade" / "src" / "FlintTrade" / "README.md",
        "workspace": home / ".flinttrade" / "workspace.json",
        "vault": home / ".flinttrade" / "credentials.db",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return paths


def _plant_macos_footprint(home: Path) -> dict[str, Path]:
    lib = home / "Library"
    paths = {
        "app_bundle": home / "Applications" / "FlintTrade.app" / "Contents" / "Info.plist",
        "caches": lib / "Caches" / BUNDLE_ID / "cache",
        "http_storages": lib / "HTTPStorages" / BUNDLE_ID / "store",
        "bundle_app_support": lib / "Application Support" / BUNDLE_ID / "config",
        "saved_state": lib / "Saved Application State" / f"{BUNDLE_ID}.savedState" / "state",
        "logs": lib / "Logs" / BUNDLE_ID / "app.log",
        "prefs": lib / "Preferences" / f"{BUNDLE_ID}.plist",
        "launch_log": home / ".local" / "state" / "flinttrade" / "desktop-launch.log",
        "src_clone": home / ".flinttrade" / "src" / "FlintTrade" / "README.md",
        "webview_storage": lib / "WebKit" / BUNDLE_ID / "WebsiteData" / "LocalStorage" / "notes",
        "workspace": lib / "Application Support" / "flinttrade" / "workspace.json",
        "vault": lib / "Application Support" / "flinttrade" / "credentials.db",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return paths


MACOS_RESIDUE_KEYS = (
    "app_bundle",
    "caches",
    "http_storages",
    "bundle_app_support",
    "saved_state",
    "logs",
    "prefs",
    "launch_log",
    "src_clone",
)


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
def test_linux_uninstall_removes_residue_and_keeps_all_data(tmp_path: Path) -> None:
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
        "webview_cache",
        "webview_config",
        "src_clone",
    ):
        assert not paths[key].exists(), f"{key} should have been removed: {paths[key]}"
    # BOTH data surfaces survive a default uninstall: the workspace (vault,
    # journals, settings) and the WebView storage (in-app saved content).
    assert paths["workspace"].exists()
    assert paths["vault"].exists()
    assert paths["webview_storage"].exists()
    assert "Workspace data kept" in result.stdout
    assert "In-app saved content kept" in result.stdout


@pytest.mark.unit
def test_linux_uninstall_purge_yes_deletes_all_data(tmp_path: Path) -> None:
    paths = _plant_linux_footprint(tmp_path)

    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 0, result.stderr
    assert not paths["workspace"].exists()
    assert not paths["vault"].exists()
    assert not paths["webview_storage"].exists()
    assert not (tmp_path / ".flinttrade").exists()


@pytest.mark.unit
def test_linux_uninstall_purge_without_consent_refuses_non_interactively(tmp_path: Path) -> None:
    paths = _plant_linux_footprint(tmp_path)

    result = _run(tmp_path, "--purge", os_name="Linux")

    assert result.returncode == 0, result.stderr
    # No TTY and no --yes: the purge must refuse rather than block or delete.
    assert paths["workspace"].exists()
    assert paths["vault"].exists()
    assert paths["webview_storage"].exists()
    assert "data kept" in result.stdout.lower()


@pytest.mark.unit
def test_installer_consent_env_var_does_not_authorise_purge(tmp_path: Path) -> None:
    """FLINTTRADE_YES belongs to the INSTALL scripts (helper-install consent).
    It must never double as purge consent — only the uninstall-specific
    FLINTTRADE_UNINSTALL_YES (or --yes) may skip the confirmation."""
    paths = _plant_linux_footprint(tmp_path)

    refused = _run(tmp_path, "--purge", os_name="Linux", extra_env={"FLINTTRADE_YES": "1"})

    assert refused.returncode == 0, refused.stderr
    assert paths["workspace"].exists()
    assert paths["vault"].exists()

    purged = _run(
        tmp_path,
        os_name="Linux",
        extra_env={"FLINTTRADE_UNINSTALL_PURGE": "1", "FLINTTRADE_UNINSTALL_YES": "1"},
    )

    assert purged.returncode == 0, purged.stderr
    assert not paths["workspace"].exists()
    assert not paths["vault"].exists()


@pytest.mark.unit
def test_purge_honours_workspace_dir_override(tmp_path: Path) -> None:
    """The backend resolves FLINTTRADE_WORKSPACE_DIR > FLINTTRADE_HOME >
    platform default; purging the hardcoded default while the real vault
    lives elsewhere would report success and leave the data on disk."""
    _plant_linux_footprint(tmp_path)
    override = tmp_path / "custom-workspace"
    override.mkdir()
    (override / "credentials.db").write_text("x")

    result = _run(
        tmp_path,
        "--purge",
        "--yes",
        os_name="Linux",
        extra_env={"FLINTTRADE_WORKSPACE_DIR": str(override)},
    )

    assert result.returncode == 0, result.stderr
    assert not override.exists()


@pytest.mark.unit
def test_macos_uninstall_removes_residue_and_keeps_all_data(tmp_path: Path) -> None:
    paths = _plant_macos_footprint(tmp_path)

    result = _run(tmp_path, os_name="Darwin")

    assert result.returncode == 0, result.stderr
    for key in MACOS_RESIDUE_KEYS:
        assert not paths[key].exists(), f"{key} should have been removed: {paths[key]}"
    assert paths["webview_storage"].exists()
    assert paths["workspace"].exists()
    assert paths["vault"].exists()
    assert "Workspace data kept" in result.stdout
    assert "In-app saved content kept" in result.stdout


@pytest.mark.unit
def test_macos_uninstall_purge_yes_deletes_all_data(tmp_path: Path) -> None:
    paths = _plant_macos_footprint(tmp_path)

    result = _run(tmp_path, "--purge", "--yes", os_name="Darwin")

    assert result.returncode == 0, result.stderr
    assert not paths["workspace"].exists()
    assert not paths["vault"].exists()
    assert not paths["webview_storage"].exists()
    assert not (tmp_path / ".flinttrade").exists()


@pytest.mark.unit
def test_macos_dry_run_lists_residue_and_deletes_nothing(tmp_path: Path) -> None:
    paths = _plant_macos_footprint(tmp_path)
    # An empty legacy dir too: dry-run must not even rmdir it (regression pin
    # for the unguarded rmdir the review caught).
    empty_legacy = tmp_path / ".flinttrade-empty-probe"
    (tmp_path / ".flinttrade" / "src").mkdir(parents=True, exist_ok=True)
    empty_legacy.mkdir()

    result = _run(tmp_path, "--dry-run", os_name="Darwin")

    assert result.returncode == 0, result.stderr
    for path in paths.values():
        assert path.exists(), f"dry-run must not delete {path}"
    assert f"Library/Caches/{BUNDLE_ID}" in result.stdout
    # The WebView storage is data — a default run must not even propose it.
    assert f"would remove {tmp_path}/Library/WebKit/{BUNDLE_ID}" not in result.stdout
    assert "nothing was deleted" in result.stdout.lower()


@pytest.mark.unit
def test_macos_dry_run_keeps_empty_legacy_dir(tmp_path: Path) -> None:
    legacy = tmp_path / ".flinttrade"
    legacy.mkdir()

    result = _run(tmp_path, "--dry-run", os_name="Darwin")

    assert result.returncode == 0, result.stderr
    assert legacy.exists(), "--dry-run must not rmdir the empty legacy dir"


@pytest.mark.unit
def test_uninstall_reports_clean_when_nothing_is_installed(tmp_path: Path) -> None:
    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stderr
    assert "does not appear to be installed" in result.stdout


@pytest.mark.unit
def test_nsis_uninstall_hook_is_wired_and_exists() -> None:
    """The native Windows uninstaller must be able to remove ALL app data.

    Tauri's stock "Delete the application data" checkbox only removes the
    bundle-id folders; the workspace at %APPDATA%\\flinttrade (credential
    vault, journals, settings) needs the installerHooks file to be wired.
    """
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    hooks_ref = conf["bundle"]["windows"]["nsis"]["installerHooks"]
    assert hooks_ref == "./windows/uninstall-hooks.nsh"
    assert NSIS_HOOKS.is_file(), "installerHooks points at a missing file"


@pytest.mark.unit
def test_nsis_uninstall_hook_deletes_only_behind_consent_and_guards() -> None:
    """Every deletion in the hook must sit behind (a) the interactive
    checkbox, (b) the update-mode guard, and (c) the explicit vault-naming
    MessageBox — and nothing deletion-like may exist outside that region, so
    a silent (/S) or auto-update uninstall can never wipe trading data."""
    text = NSIS_HOOKS.read_text(encoding="utf-8")
    # NSIS charset detection for included files is fragile; stay pure ASCII.
    assert text.isascii(), "uninstall-hooks.nsh must be pure ASCII"
    # Positional pins run over code only — the header comments narrate the
    # very commands being pinned and would otherwise satisfy the matches.
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(";")
    )
    # Whole-line macro-name pin: a renamed macro would make the template's
    # !ifmacrodef guard silently drop the hook.
    assert re.search(r"^!macro NSIS_HOOK_POSTUNINSTALL\s*$", code, re.M)

    checkbox = code.index("${If} $DeleteAppDataCheckboxState = 1")
    update_guard = code.index("${AndIf} $UpdateMode <> 1")
    consent_box = code.index("MessageBox MB_YESNO")
    keep_label = code.rindex("ft_uninstall_keep_workspace:")
    macro_end = code.index("!macroend")

    assert checkbox < update_guard < consent_box < keep_label < macro_end
    # The consent MessageBox names the vault and refuses by default in any
    # silent context, jumping past the deletions on No.
    assert "/SD IDNO IDNO ft_uninstall_keep_workspace" in code[consent_box:keep_label]
    assert "credential vault" in code[consent_box:keep_label]

    deletions = [m.start() for m in re.finditer(r"RMDir /r", code)]
    assert len(deletions) == 2, "expected exactly the two workspace deletions"
    for idx in deletions:
        assert consent_box < idx < keep_label, "deletion outside the consented region"
    # Locked-file failures must be surfaced, not silently dropped.
    clear_errors = code.index("ClearErrors")
    assert consent_box < clear_errors < deletions[0]
    assert "${If} ${Errors}" in code[deletions[-1] : keep_label]
    # Nothing deletion-like after the keep label (the unguarded tail region).
    tail = code[keep_label:]
    assert not re.search(r"RMDir|Delete |Rename ", tail), "deletion after the guard region"


@pytest.mark.unit
def test_nsis_uninstall_hook_compiles_when_makensis_works(tmp_path: Path) -> None:
    """Compile the hook via makensis inside a minimal harness that mirrors the
    Tauri template's context (LogicLib + the checkbox/update-mode vars).

    The macro is inserted UNCONDITIONALLY (no !ifmacrodef): a renamed macro
    must fail this compile loudly instead of no-oping the harness. Skips when
    makensis is absent or its toolchain is broken (some builds abort with
    std::bad_alloc on ANY script), so a red result always means the hook
    itself failed to parse.
    """
    makensis = shutil.which("makensis")
    if not makensis:
        pytest.skip("makensis is not available on this runner")

    def compile_nsi(path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [makensis, str(path)], cwd=path.parent, text=True, capture_output=True
        )

    trivial = tmp_path / "trivial.nsi"
    trivial.write_text('Name "T"\nOutFile "t.exe"\nSection\nSectionEnd\n')
    if compile_nsi(trivial).returncode != 0:
        pytest.skip("makensis is present but its toolchain is broken")

    harness = tmp_path / "harness.nsi"
    harness.write_text(
        "Unicode true\n"
        '!include "LogicLib.nsh"\n'
        'Name "HookHarness"\n'
        'OutFile "hook-harness-setup.exe"\n'
        'InstallDir "$LOCALAPPDATA\\HookHarness"\n'
        "Var DeleteAppDataCheckboxState\n"
        "Var UpdateMode\n"
        f'!include "{NSIS_HOOKS}"\n'
        'Section "Install"\n'
        '  SetOutPath "$INSTDIR"\n'
        '  WriteUninstaller "$INSTDIR\\uninstall.exe"\n'
        "SectionEnd\n"
        'Section "Uninstall"\n'
        '  StrCpy $UpdateMode "0"\n'
        '  StrCpy $DeleteAppDataCheckboxState "0"\n'
        "  !insertmacro NSIS_HOOK_POSTUNINSTALL\n"
        "SectionEnd\n"
    )
    result = compile_nsi(harness)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
