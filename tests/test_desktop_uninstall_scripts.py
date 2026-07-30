"""Retention and purge tests for the Electron shell uninstallers."""

from __future__ import annotations

import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-uninstall.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-uninstall.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"
# The macOS uninstaller reads the bundle identifier with plutil/defaults and
# signals processes inside a .app bundle. Neither exists on Linux, where the
# script correctly refuses to remove an unverified bundle — so these tests
# must skip off Darwin, exactly as their Linux (/proc) and Windows
# (PowerShell) siblings already do.
NO_MACOS_REASON = "requires macOS bundle tooling (plutil/defaults)"
LEGACY_BUNDLE_ID = "com.flinttrade.app"


def _posix_modes_honoured() -> bool:
    """Whether the temp filesystem stores POSIX permission bits.

    The receipt guards refuse anything that is not 0700/0600, which a Windows
    filesystem can never report, so tests that plant a receipt would fail for a
    reason that has nothing to do with the uninstaller.

    Returns:
        ``True`` when a directory chmod-ed to 0700 reads back as 0700.
    """
    with tempfile.TemporaryDirectory() as raw:
        probe = Path(raw) / "probe"
        probe.mkdir()
        probe.chmod(0o700)
        return (probe.stat().st_mode & 0o777) == 0o700


POSIX_MODES = _posix_modes_honoured()
NO_POSIX_MODES_REASON = "the install receipts require a filesystem that honours POSIX modes"


def _fake_bin(tmp_path: Path, os_name: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text(f"#!/bin/sh\nprintf '%s\\n' {os_name!r}\n")
    uname.chmod(0o755)
    for tool in ("pkill",):
        shim = bin_dir / tool
        shim.write_text("#!/bin/sh\nexit 1\n")
        shim.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin"


def _run(
    tmp_path: Path,
    *flags: str,
    os_name: str,
    extra_env: dict[str, str] | None = None,
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


def _plant(paths: dict[str, Path]) -> dict[str, Path]:
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return paths


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_receipt(
    home: Path,
    *,
    platform: str,
    kind: str,
    target: Path,
    executable: Path,
    wrapper: Path | None = None,
    desktop: Path | None = None,
    icon: Path | None = None,
) -> Path:
    state = home / ".local" / "state" / "flinttrade"
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    receipt = state / "shell-install.receipt"
    receipt.write_text(
        "\n".join(
            (
                "format=flinttrade-electron-shell-v1",
                f"platform={platform}",
                f"kind={kind}",
                f"target={target.resolve()}",
                f"executable={executable.resolve()}",
                f"executable_sha256={_sha256(executable)}",
                f"wrapper={wrapper.resolve() if wrapper else ''}",
                f"desktop={desktop.resolve() if desktop else ''}",
                f"icon={icon.resolve() if icon else ''}",
                f"icon_sha256={_sha256(icon) if icon else ''}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    return receipt


def _write_linux_integration(home: Path, executable: Path, *, with_icon: bool = True) -> dict[str, Path]:
    wrapper = home / ".local" / "bin" / "flinttrade"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f'#!/bin/sh\nexec "{executable.resolve()}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    desktop = home / ".local" / "share" / "applications" / "flinttrade.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "\n".join(
            (
                "[Desktop Entry]",
                "Name=FlintTrade",
                f"Exec={wrapper.resolve()}",
                "Icon=flinttrade",
                "Type=Application",
                "Categories=Office;Finance;",
                "Comment=Open-source self-hosted trading software",
                "StartupWMClass=FlintTrade",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    integration = {"wrapper": wrapper, "desktop": desktop}
    if with_icon:
        icon = home / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / "flinttrade.png"
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes(b"proved FlintTrade icon")
        integration["icon"] = icon
    return integration


def _linux_footprint(home: Path) -> dict[str, Path]:
    appimage = home / ".local" / "bin" / "flinttrade.AppImage"
    appimage.parent.mkdir(parents=True, exist_ok=True)
    appimage.write_bytes(b"proved FlintTrade AppImage")
    appimage.chmod(0o755)
    integration = _write_linux_integration(home, appimage)
    launch_log = home / ".local" / "state" / "flinttrade" / "desktop-launch.log"
    launch_log.parent.mkdir(parents=True, exist_ok=True)
    launch_log.write_text("log", encoding="utf-8")
    receipt = _write_receipt(
        home,
        platform="Linux",
        kind="linux-appimage",
        target=appimage,
        executable=appimage,
        wrapper=integration["wrapper"],
        desktop=integration["desktop"],
        icon=integration["icon"],
    )
    paths = _plant(
        {
            "workspace": home / ".flinttrade" / "workspace.json",
            "vault": home / ".flinttrade" / "credentials.db",
            "source": home / ".flinttrade" / "src" / "FlintTrade" / "package.json",
            "tools": home / ".flinttrade" / "tools" / "node" / "node",
            "profile": home / ".config" / "flinttrade-shell" / "Local Storage" / "state",
            "legacy_cache": home / ".cache" / LEGACY_BUNDLE_ID / "cache",
            "legacy_config": home / ".config" / LEGACY_BUNDLE_ID / "prefs",
            "legacy_storage": home / ".local" / "share" / LEGACY_BUNDLE_ID / "localstorage" / "notes",
        }
    )
    paths.update(
        {
            "wrapper": integration["wrapper"],
            "appimage": appimage,
            "desktop": integration["desktop"],
            "icon": integration["icon"],
            "launch_log": launch_log,
            "receipt": receipt,
        }
    )
    return paths


def _macos_footprint(home: Path) -> dict[str, Path]:
    library = home / "Library"
    app = home / "Applications" / "FlintTrade.app"
    executable = app / "Contents" / "MacOS" / "FlintTrade"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"proved FlintTrade macOS executable")
    executable.chmod(0o755)
    plist = app / "Contents" / "Info.plist"
    with plist.open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": LEGACY_BUNDLE_ID}, handle)
    launch_log = home / ".local" / "state" / "flinttrade" / "desktop-launch.log"
    launch_log.parent.mkdir(parents=True, exist_ok=True)
    launch_log.write_text("log", encoding="utf-8")
    receipt = _write_receipt(
        home,
        platform="Darwin",
        kind="mac-app",
        target=app,
        executable=executable,
    )
    paths = _plant(
        {
            "workspace": library / "Application Support" / "flinttrade" / "workspace.json",
            "vault": library / "Application Support" / "flinttrade" / "credentials.db",
            "source": home / ".flinttrade" / "src" / "FlintTrade" / "package.json",
            "tools": home / ".flinttrade" / "tools" / "node" / "node",
            "profile": library / "Application Support" / "flinttrade-shell" / "Local Storage" / "state",
            "legacy_cache": library / "Caches" / LEGACY_BUNDLE_ID / "cache",
            "legacy_http": library / "HTTPStorages" / LEGACY_BUNDLE_ID / "cookies",
            "legacy_support": library / "Application Support" / LEGACY_BUNDLE_ID / "config",
            "legacy_saved_state": library / "Saved Application State" / f"{LEGACY_BUNDLE_ID}.savedState" / "state",
            "legacy_logs": library / "Logs" / LEGACY_BUNDLE_ID / "app.log",
            "legacy_prefs": library / "Preferences" / f"{LEGACY_BUNDLE_ID}.plist",
            "legacy_webkit": library / "WebKit" / LEGACY_BUNDLE_ID / "WebsiteData" / "notes",
        }
    )
    paths.update({"app": executable, "launch_log": launch_log, "receipt": receipt})
    return paths


SHELL_KEYS = ("wrapper", "appimage", "desktop", "icon", "launch_log", "receipt")
DATA_KEYS = (
    "workspace",
    "vault",
    "source",
    "tools",
    "profile",
    "legacy_cache",
    "legacy_config",
    "legacy_storage",
)


def _remove_linux_data_roots(home: Path) -> None:
    for relative in (
        ".flinttrade",
        ".config/flinttrade-shell",
        f".cache/{LEGACY_BUNDLE_ID}",
        f".config/{LEGACY_BUNDLE_ID}",
        f".local/share/{LEGACY_BUNDLE_ID}",
    ):
        shutil.rmtree(home / relative, ignore_errors=True)


@pytest.mark.unit
def test_unix_uninstaller_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SH)], check=True, cwd=ROOT)


@pytest.mark.unit
def test_linux_ordinary_uninstall_removes_shell_and_preserves_every_data_surface(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    for key in SHELL_KEYS:
        assert not paths[key].exists(), f"shell residue survived: {key}"
    for key in DATA_KEYS:
        assert paths[key].exists(), f"ordinary uninstall removed retained data: {key}"
    assert "workspace, Electron profile, managed source/tools" in result.stdout
    assert str(tmp_path / ".config" / "flinttrade-shell") in result.stdout


@pytest.mark.unit
def test_linux_extracted_shell_uninstall_requires_and_uses_its_exact_receipt(tmp_path: Path) -> None:
    target = tmp_path / ".local" / "opt" / "flinttrade"
    executable = target / "squashfs-root" / "AppRun"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    integration = _write_linux_integration(tmp_path, executable, with_icon=False)
    receipt = _write_receipt(
        tmp_path,
        platform="Linux",
        kind="linux-extracted",
        target=target,
        executable=executable,
        wrapper=integration["wrapper"],
        desktop=integration["desktop"],
    )

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not target.exists()
    assert not integration["wrapper"].exists()
    assert not integration["desktop"].exists()
    assert not receipt.exists()


@pytest.mark.unit
def test_linux_unreceipted_same_name_collision_is_preserved_and_fails(tmp_path: Path) -> None:
    collisions = _plant(
        {
            "wrapper": tmp_path / ".local" / "bin" / "flinttrade",
            "appimage": tmp_path / ".local" / "bin" / "flinttrade.AppImage",
            "extracted": tmp_path / ".local" / "opt" / "flinttrade" / "unrelated.txt",
            "desktop": tmp_path / ".local" / "share" / "applications" / "flinttrade.desktop",
            "icon": tmp_path / ".local" / "share" / "icons" / "hicolor" / "128x128" / "apps" / "flinttrade.png",
        }
    )

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert all(path.read_text(encoding="utf-8") == "x" for path in collisions.values())
    assert "no valid owner-local shell install receipt" in result.stdout


@pytest.mark.unit
def test_linux_receipt_does_not_authorise_an_additional_same_name_shell(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    collision = tmp_path / ".local" / "opt" / "flinttrade" / "unrelated.txt"
    collision.parent.mkdir(parents=True)
    collision.write_text("keep", encoding="utf-8")

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert paths["appimage"].exists()
    assert paths["wrapper"].exists()
    assert paths["receipt"].exists()
    assert collision.read_text(encoding="utf-8") == "keep"
    assert "not named by the install receipt" in result.stdout


@pytest.mark.unit
def test_linux_tampered_wrapper_is_not_deleted_with_the_receipted_shell(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    paths["wrapper"].write_text("#!/bin/sh\nexec unrelated\n", encoding="utf-8")
    paths["wrapper"].chmod(0o755)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert paths["appimage"].exists()
    assert paths["wrapper"].read_text(encoding="utf-8") == "#!/bin/sh\nexec unrelated\n"
    assert paths["receipt"].exists()
    assert "wrapper content is not installer-owned" in result.stdout


@pytest.mark.unit
def test_non_private_shell_receipt_is_preserved_and_fails_closed(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    paths["receipt"].chmod(0o644)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert paths["appimage"].exists()
    assert paths["receipt"].exists()
    assert "receipt is not private" in result.stdout


@pytest.mark.unit
def test_malformed_shell_receipt_field_is_preserved_and_fails_closed(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    receipt_text = paths["receipt"].read_text(encoding="utf-8")
    paths["receipt"].write_text(receipt_text.replace("kind=", "kand=", 1), encoding="utf-8")

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert paths["appimage"].exists()
    assert paths["receipt"].exists()
    assert "receipt field names are invalid" in result.stdout


@pytest.mark.unit
def test_shell_target_remove_failure_retains_receipt_for_recovery(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_rm = bin_dir / "rm"
    fake_rm.write_text(
        "#!/bin/sh\n"
        'case "$*" in *flinttrade.AppImage*) exit 73 ;; esac\n'
        'exec /bin/rm "$@"\n',
        encoding="utf-8",
    )
    fake_rm.chmod(0o755)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert paths["appimage"].exists()
    assert paths["receipt"].exists()
    assert "Keeping" in result.stdout and "receipt" in result.stdout


@pytest.mark.unit
def test_missing_linux_integration_parent_is_reported_without_removing_shell(tmp_path: Path) -> None:
    target = tmp_path / ".local" / "opt" / "flinttrade"
    executable = target / "squashfs-root" / "AppRun"
    executable.parent.mkdir(parents=True)
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    integration = _write_linux_integration(tmp_path, executable, with_icon=False)
    receipt = _write_receipt(
        tmp_path,
        platform="Linux",
        kind="linux-extracted",
        target=target,
        executable=executable,
        wrapper=integration["wrapper"],
        desktop=integration["desktop"],
    )
    integration["wrapper"].unlink()
    integration["wrapper"].parent.rmdir()

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1
    assert target.exists()
    assert receipt.exists()
    assert "wrapper parent cannot be canonicalised" in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="requires Linux /proc executable identity")
def test_direct_appimage_process_requires_exact_appimage_environment_identity(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    mounted_executable = tmp_path / ".mount_FlintTrade" / "FlintTrade"
    mounted_executable.parent.mkdir()
    shutil.copyfile("/bin/sleep", mounted_executable)
    mounted_executable.chmod(0o755)
    unrelated = tmp_path / "unrelated" / "FlintTrade"
    unrelated.parent.mkdir()
    shutil.copyfile("/bin/sleep", unrelated)
    unrelated.chmod(0o755)
    shell_process = subprocess.Popen(
        [str(mounted_executable), "30"],
        env={**os.environ, "APPIMAGE": str(paths["appimage"].resolve())},
    )
    unrelated_process = subprocess.Popen([str(unrelated), "30"])
    try:
        result = _run(tmp_path, os_name="Linux")

        shell_process.wait(timeout=5)
        assert result.returncode == 0, result.stdout + result.stderr
        assert unrelated_process.poll() is None
        assert "Stopped the proved FlintTrade shell process set" in result.stdout
    finally:
        if shell_process.poll() is None:
            shell_process.terminate()
            shell_process.wait(timeout=5)
        if unrelated_process.poll() is None:
            unrelated_process.terminate()
            unrelated_process.wait(timeout=5)


@pytest.mark.unit
def test_linux_confirmed_purge_removes_workspace_profile_source_tools_and_legacy_storage(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    for key, path in paths.items():
        assert not path.exists(), f"confirmed purge left {key}: {path}"
    assert "explicitly confirmed data was purged" in result.stdout
    assert "retained data remains" not in result.stdout


@pytest.mark.unit
def test_linux_confirmed_purge_accepts_a_genuinely_empty_home_on_bash_3(tmp_path: Path) -> None:
    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No FlintTrade data to purge." in result.stdout


@pytest.mark.unit
def test_linux_shell_only_uninstall_does_not_claim_that_data_was_retained(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    _remove_linux_data_roots(tmp_path)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not paths["appimage"].exists()
    assert "no recognised FlintTrade data was found" in result.stdout
    assert "retained data remains" not in result.stdout


@pytest.mark.unit
def test_linux_shell_only_purge_does_not_claim_confirmation_for_absent_data(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    _remove_linux_data_roots(tmp_path)

    result = _run(tmp_path, "--purge", os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not paths["appimage"].exists()
    assert "no recognised FlintTrade data was found to purge" in result.stdout
    assert "explicitly confirmed data was purged" not in result.stdout


@pytest.mark.unit
def test_linux_data_only_purge_reports_cleanup_without_claiming_shell_removal(tmp_path: Path) -> None:
    workspace = tmp_path / ".flinttrade"
    workspace.mkdir()
    (workspace / "workspace.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    (workspace / "credentials.db").write_text("x", encoding="utf-8")

    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not workspace.exists()
    assert "explicitly confirmed data was purged" in result.stdout
    assert "shell uninstalled" not in result.stdout.lower()


@pytest.mark.unit
def test_linux_unconfirmed_noninteractive_purge_preserves_data(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    result = _run(tmp_path, "--purge", os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    for key in DATA_KEYS:
        assert paths[key].exists(), f"unconfirmed purge removed {key}"
    assert "data kept" in result.stdout.lower()
    assert "retained data remains available for reinstall" in result.stdout
    assert "explicitly confirmed data was purged" not in result.stdout


@pytest.mark.unit
def test_installer_yes_does_not_authorise_uninstall_purge(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    result = _run(
        tmp_path,
        "--purge",
        os_name="Linux",
        extra_env={"FLINTTRADE_YES": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert paths["vault"].exists()
    assert paths["profile"].exists()


@pytest.mark.unit
def test_uninstall_specific_environment_can_confirm_purge(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    result = _run(
        tmp_path,
        os_name="Linux",
        extra_env={
            "FLINTTRADE_UNINSTALL_PURGE": "1",
            "FLINTTRADE_UNINSTALL_YES": "1",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not paths["vault"].exists()
    assert not paths["profile"].exists()


@pytest.mark.unit
def test_purge_honours_override_and_also_removes_platform_default(tmp_path: Path) -> None:
    paths = _linux_footprint(tmp_path)
    override = tmp_path / "custom-workspace"
    (override / "credentials.db").parent.mkdir(parents=True)
    (override / "credentials.db").write_text("x", encoding="utf-8")
    (override / "workspace.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    result = _run(
        tmp_path,
        "--purge",
        "--yes",
        os_name="Linux",
        extra_env={"FLINTTRADE_WORKSPACE_DIR": str(override)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not override.exists()
    assert not paths["workspace"].exists()
    assert str(override) in result.stdout


@pytest.mark.unit
def test_workspace_override_expands_current_user_tilde(tmp_path: Path) -> None:
    override = tmp_path / "custom-workspace"
    override.mkdir()
    (override / "credentials.db").write_text("x", encoding="utf-8")
    (override / "workspace.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    result = _run(
        tmp_path,
        "--purge",
        "--yes",
        os_name="Linux",
        extra_env={"FLINTTRADE_WORKSPACE_DIR": "~/custom-workspace"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not override.exists()


@pytest.mark.unit
def test_purge_refuses_home_as_workspace(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("x", encoding="utf-8")
    result = _run(
        tmp_path,
        "--purge",
        "--yes",
        os_name="Linux",
        extra_env={"FLINTTRADE_WORKSPACE_DIR": str(tmp_path)},
    )
    assert unrelated.exists()
    assert result.returncode == 1
    assert "Refusing to purge" in result.stdout


@pytest.mark.unit
def test_purge_refuses_unproven_arbitrary_workspace_override(tmp_path: Path) -> None:
    unrelated = tmp_path / "Documents" / "personal-notes"
    unrelated.mkdir(parents=True)
    keep = unrelated / "notes.txt"
    keep.write_text("keep", encoding="utf-8")

    result = _run(
        tmp_path,
        "--purge",
        "--yes",
        os_name="Linux",
        extra_env={"FLINTTRADE_WORKSPACE_DIR": str(unrelated)},
    )

    assert result.returncode == 1
    assert keep.read_text(encoding="utf-8") == "keep"
    assert "custom workspace identity is not proven" in result.stdout
    assert "No identity-proven FlintTrade data was eligible for purge." in result.stdout
    assert "No FlintTrade data to purge." not in result.stdout


@pytest.mark.unit
def test_purge_refuses_proven_custom_workspace_below_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    workspace = outside / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "workspace.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    (workspace / "credentials.db").write_text("keep", encoding="utf-8")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
    try:
        result = _run(
            tmp_path,
            "--purge",
            "--yes",
            os_name="Linux",
            extra_env={"FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "linked" / "workspace")},
        )

        assert result.returncode == 1
        assert (workspace / "credentials.db").read_text(encoding="utf-8") == "keep"
        assert "symbolic link" in result.stdout
    finally:
        shutil.rmtree(outside, ignore_errors=True)


@pytest.mark.unit
def test_purge_refuses_managed_data_below_symlinked_parent(tmp_path: Path) -> None:
    external = tmp_path / "external-managed-data"
    source = external / "src" / "FlintTrade" / "package.json"
    tool = external / "tools" / "node" / "node"
    _plant({"source": source, "tool": tool})
    (external / "workspace.json").write_text('{"version":"1.0.0"}', encoding="utf-8")
    (external / "credentials.db").write_text("keep", encoding="utf-8")
    (tmp_path / ".flinttrade").symlink_to(external, target_is_directory=True)

    result = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert result.returncode == 1
    assert source.read_text(encoding="utf-8") == "x"
    assert tool.read_text(encoding="utf-8") == "x"
    assert (external / "credentials.db").read_text(encoding="utf-8") == "keep"
    assert "symbolic link" in result.stdout
    assert "Uninstall finished with some paths left behind" in result.stdout
    assert "unbound variable" not in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "darwin", reason=NO_MACOS_REASON)
def test_macos_ordinary_uninstall_preserves_electron_and_legacy_profiles(tmp_path: Path) -> None:
    paths = _macos_footprint(tmp_path)
    result = _run(tmp_path, os_name="Darwin")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not paths["app"].exists()
    assert not paths["launch_log"].exists()
    for key, path in paths.items():
        if key not in {"app", "launch_log", "receipt"}:
            assert path.exists(), f"ordinary uninstall removed retained data: {key}"
    assert str(tmp_path / "Library" / "Application Support" / "flinttrade-shell") in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "darwin", reason=NO_MACOS_REASON)
def test_macos_finder_copy_without_receipt_is_refused_and_retains_data(tmp_path: Path) -> None:
    paths = _macos_footprint(tmp_path)
    paths["receipt"].unlink()

    result = _run(tmp_path, os_name="Darwin")

    assert result.returncode == 1
    assert paths["app"].exists()
    assert paths["workspace"].exists()
    assert paths["profile"].exists()
    assert "no valid owner-local shell install receipt" in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "darwin", reason=NO_MACOS_REASON)
def test_macos_uninstall_stops_only_executables_inside_the_receipted_bundle(tmp_path: Path) -> None:
    paths = _macos_footprint(tmp_path)
    bundle_executable = paths["app"]
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a native compiler is required for exact executable-path process testing")
    source = tmp_path / "sleep.c"
    source.write_text("#include <unistd.h>\nint main(void) { sleep(30); return 0; }\n", encoding="utf-8")
    subprocess.run([compiler, str(source), "-o", str(bundle_executable)], check=True)
    bundle = bundle_executable.parents[2]
    _write_receipt(
        tmp_path,
        platform="Darwin",
        kind="mac-app",
        target=bundle,
        executable=bundle_executable,
    )
    unrelated = tmp_path / "unrelated" / "FlintTrade"
    unrelated.parent.mkdir()
    subprocess.run([compiler, str(source), "-o", str(unrelated)], check=True)
    proved_process = subprocess.Popen([str(bundle_executable), "30"])
    unrelated_process = subprocess.Popen([str(unrelated), "30"])
    try:
        result = _run(tmp_path, os_name="Darwin")

        proved_process.wait(timeout=5)
        assert result.returncode == 0, result.stdout + result.stderr
        assert unrelated_process.poll() is None
        assert "Stopped the proved FlintTrade shell process set" in result.stdout
        assert not bundle.exists()
    finally:
        if proved_process.poll() is None:
            proved_process.terminate()
            proved_process.wait(timeout=5)
        if unrelated_process.poll() is None:
            unrelated_process.terminate()
            unrelated_process.wait(timeout=5)


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "darwin", reason=NO_MACOS_REASON)
def test_macos_confirmed_purge_removes_all_current_and_legacy_data(tmp_path: Path) -> None:
    paths = _macos_footprint(tmp_path)
    result = _run(tmp_path, "--purge", "--yes", os_name="Darwin")

    assert result.returncode == 0, result.stdout + result.stderr
    for key, path in paths.items():
        assert not path.exists(), f"confirmed purge left {key}: {path}"
    assert "explicitly confirmed data was purged" in result.stdout
    assert "retained data remains" not in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(sys.platform != "darwin", reason=NO_MACOS_REASON)
def test_macos_dry_run_lists_shell_without_deleting_data(tmp_path: Path) -> None:
    paths = _macos_footprint(tmp_path)
    result = _run(tmp_path, "--dry-run", os_name="Darwin")

    assert result.returncode == 0, result.stdout + result.stderr
    assert all(path.exists() for path in paths.values())
    assert "would remove" in result.stdout
    assert f"would remove {tmp_path}/Library/Application Support/flinttrade-shell" not in result.stdout
    assert "nothing was deleted" in result.stdout.lower()


@pytest.mark.unit
def test_uninstall_reports_no_shell_without_destroying_retained_data(tmp_path: Path) -> None:
    profile = tmp_path / ".config" / "flinttrade-shell" / "state"
    profile.parent.mkdir(parents=True)
    profile.write_text("x", encoding="utf-8")
    result = _run(tmp_path, os_name="Linux")
    assert result.returncode == 0, result.stdout + result.stderr
    assert profile.exists()
    assert "No FlintTrade shell was removed" in result.stdout
    assert "retained data remains available for reinstall" in result.stdout


def _write_web_receipt(home: Path, *, source: Path, tools: Path, shim: Path | None = None) -> Path:
    """Plant the owner-private receipt the one-line web installer writes.

    Args:
        home: Fake ``$HOME`` for the uninstaller run.
        source: Managed web source checkout the receipt records.
        tools: Verified-tools root the receipt records.
        shim: Launcher the receipt records; defaults to the installer-owned path.

    Returns:
        The receipt file that was written.
    """
    launcher = shim if shim is not None else home / ".local" / "bin" / "flinttrade"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if not launcher.exists():
        launcher.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
        launcher.chmod(0o755)
    state = home / ".local" / "state" / "flinttrade-web"
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    receipt = state / "web-install.receipt"
    receipt.write_text(
        "\n".join(
            (
                "format=flinttrade-web-install-v1",
                "platform=Linux",
                # as_posix() is str() on any POSIX runner and keeps the receipt
                # readable when the suite is exercised through Git Bash.
                f"shim={launcher.as_posix()}",
                f"shim_sha256={_sha256(launcher)}",
                "shortcut=",
                f"source={source.as_posix()}",
                f"tools={tools.as_posix()}",
            )
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    receipt.chmod(0o600)
    return receipt


def _web_install_footprint(home: Path) -> dict[str, Path]:
    """Plant a web install whose managed source sits outside ``~/.flinttrade``."""
    source = home / "custom-src"
    source.mkdir(parents=True, exist_ok=True)
    (source / "package.json").write_text("{}", encoding="utf-8")
    tools = home / ".flinttrade" / "tools"
    (tools / "node").mkdir(parents=True, exist_ok=True)
    (tools / "node" / "node").write_text("x", encoding="utf-8")
    receipt = _write_web_receipt(home, source=source, tools=tools)
    return {
        "source": source,
        "tools": tools,
        "receipt": receipt,
        "shim": home / ".local" / "bin" / "flinttrade",
    }


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_linux_ordinary_uninstall_retains_the_web_receipt_that_proves_retained_data(tmp_path: Path) -> None:
    """The receipt is the only name a custom --src checkout has; keep it while it exists."""
    paths = _web_install_footprint(tmp_path)
    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not paths["shim"].exists(), "the proved web launcher survived an ordinary uninstall"
    assert paths["source"].exists(), "an ordinary uninstall deleted the retained custom source"
    assert paths["receipt"].exists(), (
        "the receipt was deleted while the source and tools it names were retained, so a later "
        "--purge has no proof and no path for that checkout"
    )
    assert "Keeping" in result.stdout and str(paths["receipt"]) in result.stdout
    assert str(paths["source"]) in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_linux_later_purge_still_removes_the_custom_web_source_and_retires_the_receipt(tmp_path: Path) -> None:
    """An ordinary uninstall first, a --purge later: the custom checkout must still be reachable."""
    paths = _web_install_footprint(tmp_path)
    first = _run(tmp_path, os_name="Linux")
    assert first.returncode == 0, first.stdout + first.stderr
    assert paths["source"].exists()

    second = _run(tmp_path, "--purge", "--yes", os_name="Linux")

    assert second.returncode == 0, second.stdout + second.stderr
    assert str(paths["source"]) in second.stdout, "the custom web source was never offered to --purge"
    assert not paths["source"].exists(), "the custom web source survived a confirmed purge forever"
    assert not paths["tools"].exists()
    assert not paths["receipt"].exists(), "the receipt outlived the data it was retained to prove"


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_MODES, reason=NO_POSIX_MODES_REASON)
def test_linux_uninstall_removes_the_web_receipt_once_nothing_it_names_remains(tmp_path: Path) -> None:
    """With no retained source or tools left there is nothing to prove, so the receipt goes."""
    source = tmp_path / "custom-src"
    tools = tmp_path / ".flinttrade" / "tools"
    receipt = _write_web_receipt(tmp_path, source=source, tools=tools)
    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not receipt.exists(), "the receipt was retained although it named nothing that still exists"


@pytest.mark.unit
def test_linux_uninstall_reports_an_orphaned_web_launcher(tmp_path: Path) -> None:
    """The web launcher was renamed, so the unreceipted-path report must follow it."""
    launcher = tmp_path / ".local" / "bin" / "flinttrade-web"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    launcher.chmod(0o755)

    result = _run(tmp_path, os_name="Linux")

    assert result.returncode == 1, result.stdout + result.stderr
    # The script prints the path as its own shell spells it, which is not
    # str(Path) when the suite runs through Git Bash on Windows.
    assert ".local/bin/flinttrade-web" in result.stdout, (
        "an orphaned web launcher — one no web-install receipt proves — was invisible to the "
        "unreceipted-path report, so an uninstall reported success and left it behind"
    )
    assert "no valid owner-local shell install receipt proves this path" in result.stdout
    assert launcher.exists(), "an unproven path must be reported, never removed"


def _windows_web_install(home: Path) -> dict[str, Path]:
    """Plant a Windows web install whose managed source sits outside the managed root.

    The uninstaller resolves its profile folders from the environment, so the
    throwaway home has to look like a real one.

    Args:
        home: Directory to use as the profile root.

    Returns:
        The planted paths, keyed by role.
    """
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    shim_dir = local / "Programs" / "FlintTradeWeb"
    receipt_dir = local / "flinttrade-web"
    source = home / "custom-src"
    tools = home / ".flinttrade" / "tools"
    for directory in (roaming, shim_dir, receipt_dir, source, tools):
        directory.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "flinttrade-web.cmd"
    shim.write_text("@echo off\r\n", encoding="ascii", newline="")
    (source / "package.json").write_text("{}", encoding="utf-8")
    receipt = receipt_dir / "web-install.receipt"
    receipt.write_text(
        "\r\n".join(
            (
                "format=flinttrade-web-install-v1",
                "platform=Windows",
                f"shim={shim}",
                f"shim_sha256={_sha256(shim)}",
                "shortcut=",
                f"source={source}",
                f"tools={tools}",
            )
        )
        + "\r\n",
        encoding="utf-8",
        newline="",
    )
    return {"shim": shim, "receipt": receipt, "source": source, "tools": tools}


def _windows_home_env(home: Path) -> dict[str, str]:
    """Return an environment whose profile folders resolve inside ``home``.

    Args:
        home: Directory to use as the profile root.

    Returns:
        The current environment with the home-related variables replaced.
    """
    drive, _, rest = str(home).partition("\\")
    return {
        **os.environ,
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "HOMEDRIVE": drive,
        "HOMEPATH": f"\\{rest}",
        "HOME": str(home),
    }


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL or sys.platform != "win32", reason=NO_POWERSHELL_REASON)
def test_windows_ordinary_uninstall_retains_the_web_receipt_that_proves_retained_data(
    tmp_path: Path,
) -> None:
    """Parity with Linux: the receipt is the only name a custom source has."""
    paths = _windows_web_install(tmp_path)
    env = _windows_home_env(tmp_path)

    ordinary = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(PS1)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    assert ordinary.returncode == 0, ordinary.stdout + ordinary.stderr
    # Also proves the throwaway profile really is the one the script resolved.
    assert f"Keeping {paths['receipt']}" in ordinary.stdout, ordinary.stdout + ordinary.stderr
    assert not paths["shim"].exists(), "the proved web launcher survived an ordinary uninstall"
    assert paths["source"].exists(), "an ordinary uninstall deleted the retained custom source"
    assert paths["receipt"].exists(), (
        "the receipt was deleted while the source and tools it names were retained, so a later "
        "-Purge has no proof and no path for that checkout"
    )

    # A dry-run purge deletes nothing, and still has to be able to FIND the
    # custom source — which it can only do through the retained receipt.
    later = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(PS1), "-Purge", "-Yes", "-DryRun"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    assert later.returncode == 0, later.stdout + later.stderr
    assert f"would DELETE FlintTrade data at {paths['source']}" in later.stdout, (
        "the custom web source was never offered to a later -Purge"
    )
    assert paths["source"].exists(), "a dry-run purge must delete nothing"


@pytest.mark.unit
def test_windows_ordinary_uninstall_keeps_the_receipt_that_proves_retained_web_data() -> None:
    """Parity with the POSIX fix: the receipt is the only name a custom source has.

    Deleting it during an ordinary uninstall left a later ``-Purge`` with no
    proof and no path, so a custom web source outside the managed root could
    never be purged again.
    """
    text = PS1.read_text(encoding="utf-8")
    removal_start = text.index("function Remove-ProvenWebInstall")
    removal = text[removal_start : text.index("\n}\n", removal_start)]
    assert "Test-WebInstallDataStillPresent" in removal, (
        "Remove-ProvenWebInstall still deletes the web-install receipt unconditionally"
    )
    assert removal.index("Test-WebInstallDataStillPresent") < removal.index(
        "Remove-IfExists $WebReceiptPath"
    ), "the retained-data check must gate the receipt removal, not follow it"
    assert "it is the only proof of the retained web-install data below" in removal

    assert "function Test-WebInstallDataStillPresent" in text
    assert "function Remove-RetainedWebReceipt" in text
    # The retained receipt is retired only once a purge in the same run has
    # removed everything it named, exactly as the POSIX uninstaller does.
    retire = text[text.index("function Remove-RetainedWebReceipt") :]
    retire = retire[: retire.index("\n}\n")]
    assert "if (Test-WebInstallDataStillPresent) { return }" in retire
    assert "Remove-IfExists $WebReceiptPath" in retire
    ordinary_start = text.index("} elseif ($dataTargets)")
    assert "Remove-RetainedWebReceipt" in text[ordinary_start:], (
        "the retained receipt must be retired after the purge/keep decision, so a confirmed "
        "purge in the same run still retires it"
    )
    assert text.index("Remove-RetainedWebReceipt", ordinary_start) < text.index(
        "if ($DryRun) {\n    Say \"Dry run complete", ordinary_start
    )


@pytest.mark.unit
def test_windows_uninstaller_tracks_electron_builder_and_retention_contract() -> None:
    text = PS1.read_text(encoding="utf-8")
    lower = text.lower()
    assert "[environment+specialfolder]::localapplicationdata" in lower
    assert 'join-path $localappdataroot "programs\\flinttrade"' in lower
    assert '"uninstall flinttrade.exe"' in lower
    assert "get-installentries" in lower and 'displayname -ceq "flinttrade"' in lower
    assert "[environment+specialfolder]::applicationdata" in lower
    assert 'join-path $roamingappdataroot "flinttrade-shell"' in lower
    assert 'join-path $managedroot "src"' in lower
    assert 'join-path $managedroot "tools"' in lower
    assert "com.flinttrade.app" in lower
    assert "test-provencustomworkspace" in lower
    assert "get-proveninstallrecord" in lower
    assert "uninstallstring" in lower and "displayicon" in lower and "installlocation" in lower
    assert 'split-path -leaf $registeredfull) -cne "uninstall flinttrade.exe"' in lower
    assert "test-allowedinstalldirectory" in lower
    assert "test-safeinstalldirectory" not in lower
    assert "get-uninstallerpaths" not in lower
    assert "reparsepoint" in lower
    assert "test-pathcontainsreparsepoint" in lower
    stop_proven = text[text.index("function Stop-ProvenShellProcesses") : text.index("function Get-ShortcutTarget")]
    assert 'Get-Process -Name "FlintTrade"' in stop_proven
    assert "Resolve-Path -LiteralPath ([string]$process.Path)" in stop_proven
    assert "StartTime.ToFileTimeUtc()" in stop_proven
    assert "Get-Process -Id $process.Id" in stop_proven
    assert "$currentIdentity -ne $processIdentity" in stop_proven
    assert "OrdinalIgnoreCase" in stop_proven
    assert text.index("$candidateRecords =") < text.index("Stop-ProvenShellProcesses $record")
    execution_guard = text[
        text.index("Stop-ProvenShellProcesses $record") : text.index("if ($record) {\n    if ($DryRun)")
    ]
    assert "Get-ItemProperty -LiteralPath $record.RegistryPath" in execution_guard
    assert "Get-ProvenInstallRecord $executionEntry" in execution_guard
    assert "changed before execution" in execution_guard
    assert "would stop the exact FlintTrade desktop shell" not in text
    install_proof = text[text.index("function Get-ProvenInstallRecord") : text.index("function Stop-ProvenShellProcesses")]
    assert "Test-PathContainsReparsePoint $directoryFull" in install_proof
    assert "$uninstaller.Attributes -band [System.IO.FileAttributes]::ReparsePoint" in install_proof
    assert "$executable.Attributes -band [System.IO.FileAttributes]::ReparsePoint" in install_proof
    assert "InstallLocation" in install_proof and "QuietUninstallString" in install_proof
    assert 'Start-Process -FilePath $record.UninstallerPath' in text
    assert 'Start-Process -FilePath $uninstaller' not in text
    assert "Remove-IfExists $record.Directory" not in text
    assert "preserving it and its registry proof for retry" in text
    shortcut_cleanup = text[text.index("function Get-ShortcutTarget") : text.index("$installEntries =")]
    assert "WScript.Shell" in shortcut_cleanup
    assert "$Record.ExecutablePath.Equals($target" in shortcut_cleanup
    assert "Test-PathContainsReparsePoint $shortcutPath" in shortcut_cleanup
    assert "$children.Count -eq 0" in shortcut_cleanup
    assert "Remove-Item -LiteralPath $shortcutDirectory -Recurse" not in shortcut_cleanup
    assert "Leaving an unproven same-name install directory" in text
    reparse_guard = text[text.index("function Test-PathContainsReparsePoint") : text.index("$dataTargets =")]
    assert "foreach ($component" in reparse_guard
    assert "if (Test-PathContainsReparsePoint $Target)" in reparse_guard
    assert "5100" not in text and "Get-NetTCPConnection" not in text
    assert "$script:RemovedAny = $true" in text[text.index("$process = Start-Process") :]
    proven_cleanup = text[text.index("if ($record)", text.index("Remove-ProvenShortcuts $record")) : text.index("function Get-DataTargets")]
    assert "Test-RegistryEntryStillBoundToRecord" in proven_cleanup
    assert proven_cleanup.index("Test-Path -LiteralPath $record.RegistryPath") < proven_cleanup.index(
        "Remove-Item -LiteralPath $record.RegistryPath"
    )

    data_start = text.index("$dataTargets = @(Get-DataTargets)")
    purge_start = text.index("if ($Purge)", data_start)
    ordinary_start = text.index("} elseif ($dataTargets)", purge_start)
    purge_branch = text[purge_start:ordinary_start]
    assert "$purgeTargets = @($dataTargets | Where-Object { Test-SafePurgeTarget $_ })" in purge_branch
    assert "$purgeTargets | ForEach-Object { Say \"  $_\"; Remove-IfExists $_ }" in purge_branch
    assert "$script:PurgeCompleted = $true" in purge_branch
    assert "$script:PurgedDataAny = $true" in purge_branch
    assert "$dataTargets | Where-Object { Test-SafePurgeTarget $_ }" not in text[:purge_start]
    assert "Remove-IfExists $_" not in text[ordinary_start:]
    assert '$dataTargets | ForEach-Object { Say "  $_" }' in text[ordinary_start:]
    assert "$script:PurgedDataAny -and $script:PurgeCompleted" in text
    assert "outside the current user's home" in text
    assert "$script:DataRetainedAny = $true" in text
    assert "explicitly confirmed data was purged" in text
    # The retired pre-Electron shell at %LOCALAPPDATA%\FlintTrade may only ever
    # be deleted through an identity-proven legacy record (directory + exact
    # NSIS uninstaller + a registry entry naming it), never by assuming the
    # path directly. The script spells the path via $LocalAppDataRoot now, so
    # pin the proof requirement rather than the old variable spelling.
    assert 'Join-Path $LocalAppDataRoot "FlintTrade"' in text
    assert "Remove-IfExists $LegacyShellInstallDir" not in text
    assert "Remove-IfExists $DefaultInstallDir" not in text
    legacy_proof = text[
        text.index("function Get-ProvenLegacyShellRecord") : text.index("function Remove-ProvenLegacyShell")
    ]
    assert "no registry entry proves its uninstaller" in legacy_proof
    assert 'Join-Path $canonicalDirectory "uninstall.exe"' in legacy_proof
    legacy_removal_start = text.index("function Remove-ProvenLegacyShell")
    legacy_removal = text[
        legacy_removal_start : text.index("Remove-ProvenWebInstall", legacy_removal_start)
    ]
    assert "if (-not $LegacyRecord) { return }" in legacy_removal
    assert "Remove-IfExists $LegacyRecord.Directory" in legacy_removal
    assert "Remove-ProvenLegacyShell $script:LegacyShellRecord" in text


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL or sys.platform != "win32", reason=NO_POWERSHELL_REASON)
def test_windows_ordinary_dry_run_reports_unproven_custom_workspace_without_purge_admission(tmp_path: Path) -> None:
    workspace = tmp_path / "unproven-custom-workspace"
    workspace.mkdir()
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(PS1), "-DryRun"],
        cwd=ROOT,
        env={**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(workspace) in result.stdout
    assert "data was kept" in result.stdout
    assert "custom workspace identity is not proven" not in result.stdout
    assert workspace.is_dir()


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL or sys.platform != "win32", reason=NO_POWERSHELL_REASON)
def test_windows_purge_dry_run_still_refuses_unproven_custom_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "unproven-custom-workspace"
    workspace.mkdir()
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(PS1), "-Purge", "-Yes", "-DryRun"],
        cwd=ROOT,
        env={**os.environ, "FLINTTRADE_WORKSPACE_DIR": str(workspace)},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "custom workspace identity is not proven" in result.stdout
    assert f"would DELETE FlintTrade data at {workspace}" not in result.stdout
    assert workspace.is_dir()


@pytest.mark.unit
def test_uninstallers_do_not_guess_backend_ownership_by_port_or_name_substring() -> None:
    unix = SH.read_text(encoding="utf-8")
    windows = PS1.read_text(encoding="utf-8")

    assert "pkill" not in unix
    assert "matching_shell_processes" in unix
    assert "path_inside_proven_target" in unix
    assert 'kill -TERM "$pid"' in unix
    assert "5100" not in unix and "lsof" not in unix
    assert 'Get-Process -Name "FlintTrade"' in windows
    stop_proven = windows[windows.index("function Stop-ProvenShellProcesses") : windows.index("function Get-ShortcutTarget")]
    assert "process.Path" in stop_proven
    assert "Get-NetTCPConnection" not in windows and "5100" not in windows


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_uninstaller_parses_when_powershell_is_available() -> None:
    subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            "$errors = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{PS1}', [ref]$null, [ref]$errors); "
            "if ($errors) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }",
        ],
        check=True,
        cwd=ROOT,
    )
