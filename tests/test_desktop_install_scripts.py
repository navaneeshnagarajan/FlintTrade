from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-install.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-install.ps1"

# PowerShell is absent on the Linux CI runner, so the Windows-script tests below
# must SKIP (not silently pass) there rather than give false confidence.
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"


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
                        "url": "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade_9.9.9-beta.1_aarch64.dmg",
                    },
                    {
                        "os": "macos",
                        "arch": "x64",
                        "kind": "dmg",
                        "name": "FlintTrade_9.9.9-beta.1_x64.dmg",
                        "size": 1,
                        "url": "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade_9.9.9-beta.1_x64.dmg",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.AppImage",
                        "size": 1,
                        "url": "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade_9.9.9-beta.1_amd64.AppImage",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "deb",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.deb",
                        "size": 1,
                        "url": "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade_9.9.9-beta.1_amd64.deb",
                    },
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "rpm",
                        "name": "FlintTrade-9.9.9-beta.1-1.x86_64.rpm",
                        "size": 1,
                        "url": "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade-9.9.9-beta.1-1.x86_64.rpm",
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
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
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
            # Offline coverage of the download+verify path: allow the local
            # file:// asset URL (production stays pinned to the GitHub release
            # path; see download_release_asset).
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
        },
        text=True,
        capture_output=True,
    )

    assert "Verified SHA-256 checksum" in result.stdout
    assert (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


def test_unix_installer_aborts_on_checksum_mismatch(tmp_path: Path) -> None:
    """A tampered asset (digest ≠ file) must abort the install, never run it.

    Guards the security-critical reject branch (flinttrade-install.sh
    ``verify_sha256`` → ``die "Checksum mismatch"``). A broken or inverted
    check would otherwise ship green off the success-path test alone.
    """
    appimage = tmp_path / "FlintTrade_9.9.9-beta.1_amd64.AppImage"
    appimage.write_bytes(b"real payload")
    wrong_digest = "0" * 64  # deliberately not the file's sha256
    manifest = tmp_path / "tampered.json"
    manifest.write_text(
        json.dumps(
            {
                "tag": "v9.9.9-beta.1",
                "version": "9.9.9-beta.1",
                "channel": "beta",
                "prerelease": True,
                "published_at": "2026-07-08T00:00:00Z",
                "html_url": "https://github.com/navaneeshnagarajan/FlintTrade/releases",
                "assets": [
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": appimage.name,
                        "size": appimage.stat().st_size,
                        "url": appimage.as_uri(),
                        "sha256": wrong_digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SH), "--no-launch"],
        check=False,
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": manifest.as_uri(),
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Checksum mismatch" in (result.stdout + result.stderr)
    # The installer must NOT have been placed from a tampered download.
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


def test_unix_installer_refuses_asset_url_outside_official_release_path(tmp_path: Path) -> None:
    """A tampered manifest pointing an installer at a foreign host is refused."""
    manifest = tmp_path / "evil.json"
    manifest.write_text(
        json.dumps(
            {
                "tag": "v9.9.9-beta.1",
                "version": "9.9.9-beta.1",
                "channel": "beta",
                "prerelease": True,
                "published_at": "2026-07-08T00:00:00Z",
                "html_url": "https://github.com/navaneeshnagarajan/FlintTrade/releases",
                "assets": [
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.AppImage",
                        "size": 1,
                        "url": "https://evil.example/FlintTrade_9.9.9-beta.1_amd64.AppImage",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SH), "--no-launch"],
        check=False,
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": manifest.as_uri(),
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "outside the official release path" in (result.stdout + result.stderr)


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
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
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
        # Detach the controlling terminal so the missing-uv consent() prompt
        # sees an unopenable /dev/tty and declines, matching headless installs.
        # Without this the test would block on a real terminal locally.
        start_new_session=True,
    )

    assert result.returncode != 0
    assert "Source-build mode enabled" in result.stdout
    assert "source-build prerequisites" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_installer_parses_when_powershell_is_available() -> None:
    subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            f"$null = [scriptblock]::Create((Get-Content -Raw {str(PS1)!r}))",
        ],
        check=True,
        cwd=ROOT,
    )


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_installer_binary_dry_run_selects_setup_exe_when_powershell_is_available(tmp_path: Path) -> None:
    pwsh = POWERSHELL
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
                url = "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/v9.9.9-beta.1/FlintTrade_9.9.9-beta.1_x64-setup.exe"
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


def _appimage_manifest(tmp_path: Path, payload: Path) -> str:
    """Write a single-asset (linux/x64/appimage) manifest for ``payload`` and
    return its ``file://`` URI, with a correct sha256 so verify_sha256 passes."""
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest = tmp_path / f"manifest-{payload.name}.json"
    manifest.write_text(
        json.dumps(
            {
                "tag": "v9.9.9-beta.1",
                "version": "9.9.9-beta.1",
                "channel": "beta",
                "prerelease": True,
                "published_at": "2026-07-08T00:00:00Z",
                "html_url": "https://github.com/navaneeshnagarajan/FlintTrade/releases",
                "assets": [
                    {
                        "os": "linux",
                        "arch": "x64",
                        "kind": "appimage",
                        "name": "FlintTrade_9.9.9-beta.1_amd64.AppImage",
                        "size": payload.stat().st_size,
                        "url": payload.as_uri(),
                        "sha256": digest,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest.as_uri()


@pytest.mark.unit
def test_source_build_tag_resolution_prefers_stable_over_prerelease(tmp_path: Path) -> None:
    """A stable release must outrank its own prerelease at equal version, while a
    newer prerelease still beats an older stable (guards the resolve_latest_tag
    semver tie-break used by the source-build default target)."""

    def resolve(tags: str) -> str:
        result = subprocess.run(
            ["bash", str(SH)],
            input=tags,
            check=True,
            cwd=ROOT,
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": str(tmp_path),
                "FLINTTRADE_RESOLVE_TAGS_ONLY": "1",
            },
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()

    # Stable v9.9.9 wins over its own beta/rc at the same version.
    assert resolve("v9.9.8\nv9.9.9-beta.1\nv9.9.9-rc.2\nv9.9.9\n") == "v9.9.9"
    # A newer prerelease still beats an older stable ("newest overall" preserved).
    assert resolve("v9.9.8\nv9.9.9-beta.1\n") == "v9.9.9-beta.1"
    # Ordering across prereleases of the same core still holds.
    assert resolve("v9.9.9-beta.1\nv9.9.9-beta.2\n") == "v9.9.9-beta.2"


@pytest.mark.unit
def test_unix_installer_signals_update_handoff_for_desktop_updater(tmp_path: Path) -> None:
    """When the desktop shell sets FLINTTRADE_UPDATE_HANDOFF, a real install must
    touch that marker (so the shell knows the download verified and it may quit),
    and a --dry-run must NOT — otherwise the shell would vanish on a no-op run."""
    payload = tmp_path / "FlintTrade_9.9.9-beta.1_amd64.AppImage"
    payload.write_bytes(b"fake appimage payload")
    manifest_uri = _appimage_manifest(tmp_path, payload)
    handoff = tmp_path / "update_handoff"

    base_env = {
        "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
        "HOME": str(tmp_path),
        "FLINTTRADE_DESKTOP_RELEASE_API": manifest_uri,
        "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
        "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
    }

    # --dry-run: the marker must NOT be created (no real install happened).
    subprocess.run(
        ["bash", str(SH), "--no-launch", "--dry-run"],
        check=True,
        cwd=ROOT,
        env=base_env,
        text=True,
        capture_output=True,
    )
    assert not handoff.exists()

    # Real install: the marker is created before the bundle is replaced.
    subprocess.run(
        ["bash", str(SH), "--no-launch"],
        check=True,
        cwd=ROOT,
        env=base_env,
        text=True,
        capture_output=True,
    )
    assert handoff.exists()
    assert (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
def test_unix_installer_appimage_updates_running_path_in_place(tmp_path: Path) -> None:
    """When launched from a running AppImage (the runtime exports $APPIMAGE), the
    updater must replace THAT file in place — not drop a second copy under
    ~/.local/bin — so the operator's launched binary is the one that updates."""
    running = tmp_path / "custom" / "FlintTrade.AppImage"
    running.parent.mkdir(parents=True)
    running.write_bytes(b"OLD VERSION")
    running.chmod(0o755)

    payload = tmp_path / "FlintTrade_9.9.9-beta.1_amd64.AppImage"
    payload.write_bytes(b"NEW VERSION PAYLOAD")
    manifest_uri = _appimage_manifest(tmp_path, payload)

    subprocess.run(
        ["bash", str(SH), "--no-launch"],
        check=True,
        cwd=ROOT,
        env={
            "PATH": _fake_uname(tmp_path, "Linux", "x86_64"),
            "HOME": str(tmp_path),
            "FLINTTRADE_DESKTOP_RELEASE_API": manifest_uri,
            "FLINTTRADE_ALLOW_LOCAL_ASSET": "1",
            "APPIMAGE": str(running),
        },
        text=True,
        capture_output=True,
    )

    # The running image was updated in place; no stray copy under ~/.local/bin.
    assert running.read_bytes() == b"NEW VERSION PAYLOAD"
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()
