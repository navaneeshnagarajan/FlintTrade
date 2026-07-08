from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-install.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-install.ps1"


def _manifest(tmp_path: Path) -> str:
    path = tmp_path / "desktop-release.json"
    path.write_text(
        json.dumps(
            {
                "tag": "v9.9.9-beta.1",
                "version": "9.9.9-beta.1",
                "channel": "beta",
                "prerelease": True,
                "published_at": "2026-07-08T00:00:00Z",
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "os": "macos",
                        "arch": "arm64",
                        "kind": "dmg",
                        "name": "FlintTrade_9.9.9-beta.1_aarch64.dmg",
                        "size": 1,
                        "url": "https://example.invalid/mac.dmg",
                    },
                    {
                        "os": "macos",
                        "arch": "x64",
                        "kind": "dmg",
                        "name": "FlintTrade_9.9.9-beta.1_x64.dmg",
                        "size": 1,
                        "url": "https://example.invalid/mac-x64.dmg",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.AppImage",
                        "size": 1,
                        "url": "https://example.invalid/linux.AppImage",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "deb",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.deb",
                        "size": 1,
                        "url": "https://example.invalid/linux.deb",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "rpm",
                        "name": "FlintTrade-9.9.9-beta.1-1.x86_64.rpm",
                        "size": 1,
                        "url": "https://example.invalid/linux.rpm",
                    },
                ],
            }
        )
    )
    return path.as_uri()


def _fake_uname(tmp_path: Path, os_name: str, machine: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "-m" ]; then\n'
        f"  printf '%s\\n' {machine!r}\n"
        "else\n"
        f"  printf '%s\\n' {os_name!r}\n"
        "fi\n"
    )
    uname.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin"


def _run_unix_installer_dry_run(tmp_path: Path, *, os_name: str, machine: str, package: str = "appimage"):
    return subprocess.run(
        [
            "bash",
            str(SH),
            "--dry-run",
            "--no-launch",
            "--package",
            package,
        ],
        check=True,
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, os_name, machine),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": _manifest(tmp_path),
        },
        text=True,
        capture_output=True,
    )


def test_unix_installer_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SH)], check=True, cwd=ROOT)


def test_unix_installer_binary_dry_run_uses_manifest_asset(tmp_path: Path) -> None:
    result = _run_unix_installer_dry_run(tmp_path, os_name="Linux", machine="x86_64")

    assert "would download FlintTrade_9.9.9-beta.1_amd64.AppImage" in result.stdout
    assert "would install /tmp/FlintTrade_9.9.9-beta.1_amd64.AppImage" in result.stdout
    assert "uv sync" not in result.stdout


def test_unix_installer_binary_install_verifies_sha256(tmp_path: Path) -> None:
    appimage = tmp_path / "FlintTrade_9.9.9-beta.1_amd64.AppImage"
    appimage.write_bytes(b"fake appimage payload")
    digest = hashlib.sha256(appimage.read_bytes()).hexdigest()
    manifest = tmp_path / "desktop-release-with-checksum.json"
    manifest.write_text(
        json.dumps(
            {
                "tag": "v9.9.9-beta.1",
                "version": "9.9.9-beta.1",
                "channel": "beta",
                "prerelease": True,
                "published_at": "2026-07-08T00:00:00Z",
                "html_url": "https://example.invalid/release",
                "assets": [
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": appimage.name,
                        "size": appimage.stat().st_size,
                        "url": appimage.as_uri(),
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SH), "--no-launch"],
        check=True,
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": manifest.as_uri(),
        },
        text=True,
        capture_output=True,
    )

    assert "Verified SHA-256 checksum" in result.stdout
    assert (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


def test_unix_installer_refuses_warning_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "warning.json"
    manifest.write_text(json.dumps({"warning": "stale fallback", "assets": []}), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SH), "--dry-run"],
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": manifest.as_uri(),
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "fallback warning" in result.stderr


def test_unix_installer_binary_dry_run_selects_macos_dmg(tmp_path: Path) -> None:
    result = _run_unix_installer_dry_run(tmp_path, os_name="Darwin", machine="arm64")

    assert "would download FlintTrade_9.9.9-beta.1_aarch64.dmg" in result.stdout
    assert "would mount /tmp/FlintTrade_9.9.9-beta.1_aarch64.dmg" in result.stdout


def test_unix_installer_binary_dry_run_selects_linux_native_packages(tmp_path: Path) -> None:
    deb = _run_unix_installer_dry_run(tmp_path, os_name="Linux", machine="x86_64", package="deb")
    rpm = _run_unix_installer_dry_run(tmp_path, os_name="Linux", machine="x86_64", package="rpm")

    assert "would download FlintTrade_9.9.9-beta.1_amd64.deb" in deb.stdout
    assert "would install /tmp/FlintTrade_9.9.9-beta.1_amd64.deb as a .deb package" in deb.stdout
    assert "would download FlintTrade-9.9.9-beta.1-1.x86_64.rpm" in rpm.stdout
    assert "would install /tmp/FlintTrade-9.9.9-beta.1-1.x86_64.rpm as a .rpm package" in rpm.stdout


def test_unix_installer_source_mode_reports_missing_prerequisites(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SH), "--build-from-source", "--dry-run"],
        cwd=ROOT,
        env={
            "PATH": "/bin:/usr/bin",
            "HOME": str(tmp_path),
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Source-build mode enabled" in result.stdout
    assert "source-build prerequisites" in result.stderr


def test_windows_installer_parses_when_powershell_is_available() -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        return

    subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-Command",
            f"$null = [scriptblock]::Create((Get-Content -Raw {str(PS1)!r}))",
        ],
        check=True,
        cwd=ROOT,
    )


def test_windows_installer_binary_dry_run_selects_setup_exe_when_powershell_is_available(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        return

    script_path = str(PS1).replace("'", "''")
    harness = tmp_path / "windows-dry-run.ps1"
    harness.write_text(
        f"""
function Get-CimInstance {{
    [pscustomobject]@{{ Architecture = 9 }}
}}
function Invoke-RestMethod {{
    [pscustomobject]@{{
        assets = @(
            [pscustomobject]@{{
                os = "windows"
                arch = "x64"
                kind = "nsis"
                name = "FlintTrade_9.9.9-beta.1_x64-setup.exe"
                url = "https://example.invalid/flinttrade-setup.exe"
            }}
        )
    }}
}}
& '{script_path}' -DryRun -NoLaunch
exit $LASTEXITCODE
""".strip()
    )

    result = subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        check=True,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert "would download FlintTrade_9.9.9-beta.1_x64-setup.exe" in result.stdout
    assert "would run" in result.stdout
