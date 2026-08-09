"""Policy and offline integration tests for the Electron shell installers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install" / "flinttrade-install.sh"
PS1 = ROOT / "scripts" / "install" / "flinttrade-install.ps1"
REPO_SLUG = "navaneeshnagarajan/FlintTrade"
GITHUB_API_BASE = f"https://api.github.com/repos/{REPO_SLUG}"
RELEASE_DOWNLOAD_BASE = f"https://github.com/{REPO_SLUG}/releases/download"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NO_POWERSHELL_REASON = "PowerShell (pwsh/powershell) is not available on this runner"
POSIX_INSTALL_SEMANTICS = os.name != "nt"
NO_POSIX_INSTALL_REASON = (
    "the offline installer scenarios need POSIX filesystem semantics - executable bits, private "
    "0700 receipts, AppImage self-extraction and absolute POSIX $APPIMAGE paths - which a Windows "
    "host cannot report"
)
NO_POSIX_SHELL_REASON = (
    "flinttrade-install.sh refuses any host whose uname is not Linux or Darwin; install.ps1 is the "
    "Windows installer"
)


def _case_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def _asset_names(version: str) -> tuple[str, ...]:
    return (
        f"FlintTrade-{version}-mac-universal.dmg",
        f"FlintTrade-{version}-win-x64.exe",
        f"FlintTrade-{version}-linux-x64.AppImage",
        f"FlintTrade-{version}-linux-arm64.AppImage",
    )


def _release(version: str, *, prerelease: bool, draft: bool = False) -> dict[str, object]:
    tag = f"v{version}"
    assets = [
        {
            "name": name,
            # GitHub asset objects contain a nested uploader before the browser
            # URL. This catches flat-object parsers that accidentally worked
            # only with the retired generated metadata shape.
            "uploader": {"login": "release-bot"},
            "browser_download_url": f"{RELEASE_DOWNLOAD_BASE}/{tag}/{name}",
        }
        for name in _asset_names(version)
    ]
    assets.append(
        {
            "name": "SHA256SUMS.txt",
            "uploader": {"login": "release-bot"},
            "browser_download_url": f"{RELEASE_DOWNLOAD_BASE}/{tag}/SHA256SUMS.txt",
        }
    )
    return {
        "tag_name": tag,
        "name": f"FlintTrade {tag} with {{brace-bearing notes}}",
        "draft": draft,
        "prerelease": prerelease,
        "assets": assets,
    }


def _fake_uname(tmp_path: Path, os_name: str, machine: str) -> Path:
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
    return bin_dir


def _fake_curl(tmp_path: Path) -> None:
    curl = tmp_path / "bin" / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'out=""; url=""\n'
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        '    -o) out="$2"; shift 2 ;;\n'
        '    -H) shift 2 ;;\n'
        '    -*) shift ;;\n'
        '    *) url="$1"; shift ;;\n'
        "  esac\n"
        "done\n"
        '[ -n "${FAKE_CURL_LOG:-}" ] && printf "%s\\n" "$url" >> "$FAKE_CURL_LOG"\n'
        'case "$url" in\n'
        '  */SHA256SUMS.txt) src="$FAKE_SUMS" ;;\n'
        '  */FlintTrade-*) src="$FAKE_ASSET" ;;\n'
        '  *) src="$FAKE_RELEASE" ;;\n'
        "esac\n"
        'if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi\n'
    )
    curl.chmod(0o755)


def _fixture_env(
    tmp_path: Path,
    *,
    os_name: str = "Linux",
    machine: str = "x86_64",
    release_json: object | None = None,
    asset_bytes: bytes = b"fake Electron shell",
    sums_text: str | None = None,
) -> dict[str, str]:
    bin_dir = _fake_uname(tmp_path, os_name, machine)
    _fake_curl(tmp_path)
    release = release_json if release_json is not None else _release("9.9.9-beta.1", prerelease=True)
    release_path = tmp_path / "release.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    asset_path = tmp_path / "shell-asset"
    asset_path.write_bytes(asset_bytes)
    digest = hashlib.sha256(asset_bytes).hexdigest()
    if sums_text is None:
        sums_text = "".join(f"{digest}  {name}\n" for name in _asset_names("9.9.9-beta.1"))
    sums_path = tmp_path / "SHA256SUMS.txt"
    sums_path.write_text(sums_text, encoding="utf-8")
    return {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(tmp_path),
        "FAKE_RELEASE": str(release_path),
        "FAKE_ASSET": str(asset_path),
        "FAKE_SUMS": str(sums_path),
    }


def _run(
    tmp_path: Path,
    *args: str,
    os_name: str = "Linux",
    machine: str = "x86_64",
    release_json: object | None = None,
    asset_bytes: bytes = b"fake Electron shell",
    sums_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = _fixture_env(
        tmp_path,
        os_name=os_name,
        machine=machine,
        release_json=release_json,
        asset_bytes=asset_bytes,
        sums_text=sums_text,
    )
    env.update(extra_env or {})
    if "FLINTTRADE_UPDATE_HANDOFF" in env:
        if os_name == "Darwin":
            default_asset_name = "FlintTrade-9.9.9-beta.1-mac-universal.dmg"
        else:
            arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
            default_asset_name = f"FlintTrade-9.9.9-beta.1-linux-{arch}.AppImage"
        env.setdefault("FLINTTRADE_UPDATE_ASSET_NAME", default_asset_name)
        env.setdefault("FLINTTRADE_UPDATE_ASSET_SHA256", hashlib.sha256(asset_bytes).hexdigest())
    return subprocess.run(
        ["bash", str(SH), *args],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )


def _running_appimage(tmp_path: Path) -> Path:
    running = tmp_path / "custom" / "FlintTrade.AppImage"
    running.parent.mkdir(exist_ok=True)
    running.write_bytes(b"old Electron shell")
    running.chmod(0o755)
    return running


def _plant_linux_integrations(home: Path, executable: Path) -> tuple[Path, Path]:
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
    return wrapper, desktop


@pytest.mark.unit
def test_unix_installer_is_valid_bash() -> None:
    subprocess.run(["bash", "-n", str(SH)], check=True, cwd=ROOT)


@pytest.mark.unit
def test_installers_use_only_current_electron_shell_contract() -> None:
    unix = SH.read_text(encoding="utf-8")
    windows = PS1.read_text(encoding="utf-8")
    combined = (unix + windows).lower()

    for name in (
        "FlintTrade-$version-mac-universal.dmg",
        "FlintTrade-$version-linux-$arch.AppImage",
        '"FlintTrade-$version-win-x64.exe"',
    ):
        assert name in unix + windows
    assert "SHA256SUMS.txt" in unix and "SHA256SUMS.txt" in windows
    assert "https://api.github.com/repos/$REPO_SLUG" in unix
    assert '"https://api.github.com/repos/$RepoSlug"' in windows
    for retired in (
        "desktop-manifest",
        "updater-beta",
        "updater-stable",
        "minisign",
        "flinttrade-payload",
        "src-tauri",
        "tauri build",
        "pyinstaller",
        "uv sync",
        "cargo",
        "build-backend",
        "packages/apps/terminal",
    ):
        assert retired not in combined
    assert "--package" not in unix
    assert ".deb" not in combined and ".rpm" not in combined


@pytest.mark.unit
def test_source_build_checks_native_helper_compilers_and_headers() -> None:
    unix = SH.read_text(encoding="utf-8")
    windows = PS1.read_text(encoding="utf-8")

    assert "/usr/bin/clang" in unix
    assert "/usr/bin/cc" in unix
    assert "node_api.h" in unix
    assert '"Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe"' in windows
    assert "native compiler" in unix
    assert "native compiler" in windows


@pytest.mark.unit
def test_unix_beta_channel_advances_to_newest_stable_and_same_release_sums(tmp_path: Path) -> None:
    releases = [
        _release("10.0.0", prerelease=False),
        _release("9.9.9-beta.1", prerelease=True),
    ]
    digest = hashlib.sha256(b"fake Electron shell").hexdigest()
    sums = "".join(f"{digest}  {name}\n" for name in _asset_names("10.0.0"))
    log = tmp_path / "curl.log"
    result = _run(
        tmp_path,
        "--dry-run",
        "--no-launch",
        release_json=releases,
        sums_text=sums,
        extra_env={"FAKE_CURL_LOG": str(log)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "would download FlintTrade-10.0.0-linux-x64.AppImage" in result.stdout
    assert f"{GITHUB_API_BASE}/releases?per_page=100" in log.read_text()
    assert f"{RELEASE_DOWNLOAD_BASE}/v10.0.0/SHA256SUMS.txt" in log.read_text()


@pytest.mark.unit
def test_unix_beta_channel_rejects_other_prerelease_lines_and_inconsistent_metadata(tmp_path: Path) -> None:
    releases = [
        _release("10.0.0-alpha.1", prerelease=True),
        _release("9.9.9", prerelease=True),
        _release("9.9.9-beta.2", prerelease=True),
    ]
    digest = hashlib.sha256(b"fake Electron shell").hexdigest()
    sums = "".join(f"{digest}  {name}\n" for name in _asset_names("9.9.9-beta.2"))

    result = _run(tmp_path, "--dry-run", release_json=releases, sums_text=sums)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "FlintTrade-9.9.9-beta.2-linux-x64.AppImage" in result.stdout
    assert "10.0.0-alpha.1" not in result.stdout


@pytest.mark.unit
def test_unix_stable_and_exact_ref_use_github_release_api(tmp_path: Path) -> None:
    digest = hashlib.sha256(b"fake Electron shell").hexdigest()
    stable_sums = "".join(f"{digest}  {name}\n" for name in _asset_names("10.0.0"))
    stable_log = tmp_path / "stable.log"
    stable_home = _case_dir(tmp_path, "stable")
    stable = _run(
        stable_home,
        "--dry-run",
        "--channel",
        "stable",
        release_json=_release("10.0.0", prerelease=False),
        sums_text=stable_sums,
        extra_env={"FAKE_CURL_LOG": str(stable_log)},
    )
    assert stable.returncode == 0, stable.stdout + stable.stderr
    assert f"{GITHUB_API_BASE}/releases?per_page=100" in stable_log.read_text()
    assert f"{GITHUB_API_BASE}/releases/latest" not in stable_log.read_text()
    assert "FlintTrade-10.0.0-linux-x64.AppImage" in stable.stdout

    ref_log = tmp_path / "ref.log"
    ref_home = _case_dir(tmp_path, "ref")
    ref = _run(
        ref_home,
        "--update",
        "--ref",
        "v9.9.9-beta.1",
        "--yes",
        "--dry-run",
        extra_env={"FAKE_CURL_LOG": str(ref_log)},
    )
    assert ref.returncode == 0, ref.stdout + ref.stderr
    assert f"{GITHUB_API_BASE}/releases/tags/v9.9.9-beta.1" in ref_log.read_text()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("channel", "newest_version", "middle_version", "selected_version", "prerelease"),
    [
        ("stable", "10.0.2", "10.0.1", "10.0.0", False),
        ("beta", "10.0.0-beta.3", "10.0.0-beta.2", "10.0.0-beta.1", True),
    ],
)
def test_unix_channel_skips_incomplete_or_untrusted_newer_releases(
    tmp_path: Path,
    channel: str,
    newest_version: str,
    middle_version: str,
    selected_version: str,
    prerelease: bool,
) -> None:
    newest = _release(newest_version, prerelease=prerelease)
    newest_asset = f"FlintTrade-{newest_version}-linux-x64.AppImage"
    newest["assets"] = [asset for asset in newest["assets"] if asset["name"] != newest_asset]  # type: ignore[index]
    middle = _release(middle_version, prerelease=prerelease)
    for asset in middle["assets"]:  # type: ignore[union-attr]
        if asset["name"] == "SHA256SUMS.txt":
            asset["browser_download_url"] = f"https://evil.invalid/{middle_version}/SHA256SUMS.txt"
    selected = _release(selected_version, prerelease=prerelease)
    digest = hashlib.sha256(b"fake Electron shell").hexdigest()
    sums = "".join(f"{digest}  {name}\n" for name in _asset_names(selected_version))

    result = _run(
        tmp_path,
        "--dry-run",
        "--channel",
        channel,
        release_json=[newest, middle, selected],
        sums_text=sums,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FlintTrade-{selected_version}-linux-x64.AppImage" in result.stdout
    assert newest_version not in result.stdout
    assert middle_version not in result.stdout


@pytest.mark.unit
def test_unix_channel_skips_non_semver_release_and_consumes_large_response(tmp_path: Path) -> None:
    selected = _release("9.9.9-beta.1", prerelease=True)
    unrelated = _release("99.0.0", prerelease=False)
    unrelated["tag_name"] = "nightly"
    unrelated["name"] = "unrelated stable-looking release"
    padding = [
        {
            "tag_name": f"nightly-{index}",
            "draft": True,
            "prerelease": False,
            "body": "x" * 32768,
            "assets": [],
        }
        for index in range(80)
    ]

    result = _run(
        tmp_path,
        "--dry-run",
        release_json=[selected, unrelated, *padding],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "FlintTrade-9.9.9-beta.1-linux-x64.AppImage" in result.stdout
    assert "Broken pipe" not in result.stderr


@pytest.mark.unit
def test_unix_installer_rejects_missing_or_wrong_release_checksums(tmp_path: Path) -> None:
    missing_asset_release = _release("9.9.9-beta.1", prerelease=True)
    missing_asset_release["assets"] = [
        asset for asset in missing_asset_release["assets"] if asset["name"] != "SHA256SUMS.txt"  # type: ignore[index]
    ]
    missing_asset = _run(
        _case_dir(tmp_path, "missing-asset"),
        "--dry-run",
        "--ref",
        "v9.9.9-beta.1",
        release_json=missing_asset_release,
    )
    assert missing_asset.returncode != 0
    assert "no required SHA256SUMS.txt" in missing_asset.stderr

    missing_entry = _run(
        _case_dir(tmp_path, "missing-entry"),
        "--dry-run",
        sums_text=f"{'0' * 64}  unrelated.txt\n",
    )
    assert missing_entry.returncode != 0
    assert "exactly one checksum" in missing_entry.stderr

    duplicate = _run(
        _case_dir(tmp_path, "duplicate"),
        "--dry-run",
        sums_text=(f"{'0' * 64}  FlintTrade-9.9.9-beta.1-linux-x64.AppImage\n" * 2),
    )
    assert duplicate.returncode != 0
    assert "exactly one checksum" in duplicate.stderr


@pytest.mark.unit
def test_unix_in_app_update_binds_download_to_app_attested_name_and_digest(tmp_path: Path) -> None:
    asset = b"attested Electron shell"
    digest = hashlib.sha256(asset).hexdigest()
    name = "FlintTrade-9.9.9-beta.1-linux-x64.AppImage"
    common_env = {
        "FLINTTRADE_UPDATE_HANDOFF": str(tmp_path / "handoff"),
        "FLINTTRADE_UPDATE_ASSET_NAME": name,
    }
    accepted = _run(
        _case_dir(tmp_path, "accepted"),
        "--update",
        "--ref",
        "v9.9.9-beta.1",
        "--yes",
        "--dry-run",
        asset_bytes=asset,
        extra_env={**common_env, "FLINTTRADE_UPDATE_ASSET_SHA256": digest},
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert f"would verify sha256 {digest}" in accepted.stdout

    wrong_digest = _run(
        _case_dir(tmp_path, "wrong-digest"),
        "--update",
        "--ref",
        "v9.9.9-beta.1",
        "--yes",
        "--dry-run",
        asset_bytes=asset,
        extra_env={**common_env, "FLINTTRADE_UPDATE_ASSET_SHA256": "0" * 64},
    )
    assert wrong_digest.returncode != 0
    assert "SHA256SUMS.txt did not match the app-verified" in wrong_digest.stderr

    wrong_name = _run(
        _case_dir(tmp_path, "wrong-name"),
        "--update",
        "--ref",
        "v9.9.9-beta.1",
        "--yes",
        "--dry-run",
        asset_bytes=asset,
        extra_env={
            **common_env,
            "FLINTTRADE_UPDATE_ASSET_NAME": "FlintTrade-9.9.9-beta.1-linux-arm64.AppImage",
            "FLINTTRADE_UPDATE_ASSET_SHA256": digest,
        },
    )
    assert wrong_name.returncode != 0
    assert "installer name did not match the app-verified" in wrong_name.stderr


@pytest.mark.unit
def test_unix_installer_rejects_cross_release_and_foreign_urls(tmp_path: Path) -> None:
    cross_release = _release("9.9.9-beta.1", prerelease=True)
    for asset in cross_release["assets"]:  # type: ignore[union-attr]
        if asset["name"] == "SHA256SUMS.txt":
            asset["browser_download_url"] = f"{RELEASE_DOWNLOAD_BASE}/v9.9.8/SHA256SUMS.txt"
    wrong_sums = _run(
        _case_dir(tmp_path, "cross-release"),
        "--dry-run",
        "--ref",
        "v9.9.9-beta.1",
        release_json=cross_release,
    )
    assert wrong_sums.returncode != 0
    assert "outside the selected official release" in wrong_sums.stderr

    foreign = _release("9.9.9-beta.1", prerelease=True)
    for asset in foreign["assets"]:  # type: ignore[union-attr]
        if asset["name"].endswith("linux-x64.AppImage"):
            asset["browser_download_url"] = f"https://evil.invalid/{asset['name']}"
    wrong_host = _run(
        _case_dir(tmp_path, "foreign"),
        "--dry-run",
        "--ref",
        "v9.9.9-beta.1",
        release_json=foreign,
    )
    assert wrong_host.returncode != 0
    assert "outside the selected official release" in wrong_host.stderr


@pytest.mark.unit
def test_unix_linux_x64_and_arm64_select_exact_appimages(tmp_path: Path) -> None:
    x64 = _run(_case_dir(tmp_path, "x64"), "--dry-run", machine="x86_64")
    assert x64.returncode == 0, x64.stdout + x64.stderr
    assert "FlintTrade-9.9.9-beta.1-linux-x64.AppImage" in x64.stdout

    arm = _run(_case_dir(tmp_path, "arm64"), "--dry-run", machine="aarch64")
    assert arm.returncode == 0, arm.stdout + arm.stderr
    assert "FlintTrade-9.9.9-beta.1-linux-arm64.AppImage" in arm.stdout


@pytest.mark.unit
def test_unix_macos_selects_universal_dmg(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run", os_name="Darwin", machine="arm64")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "would download FlintTrade-9.9.9-beta.1-mac-universal.dmg" in result.stdout
    assert "would mount /tmp/FlintTrade-9.9.9-beta.1-mac-universal.dmg" in result.stdout


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_appimage_install_verifies_checksum_and_signals_handoff(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = _running_appimage(tmp_path)
    parent = subprocess.Popen(["sleep", "1"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS": "5",
                "APPIMAGE": str(running),
            },
        )
    finally:
        parent.wait(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified SHA-256 checksum from the selected release" in result.stdout
    assert handoff.is_file()
    assert running.read_bytes() == b"fake Electron shell"
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_custom_appimage_update_uses_stable_desktop_wrapper(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = tmp_path / "custom target" / "FlintTrade.AppImage"
    running.parent.mkdir()
    running.write_bytes(b"old Electron shell")
    running.chmod(0o755)
    parent = subprocess.Popen(["sleep", "1"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS": "5",
                "APPIMAGE": str(running),
            },
        )
    finally:
        parent.wait(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    desktop_entry = tmp_path / ".local" / "share" / "applications" / "flinttrade.desktop"
    assert f"Exec={tmp_path}/.local/bin/flinttrade\n" in desktop_entry.read_text(encoding="utf-8")
    wrapper = tmp_path / ".local" / "bin" / "flinttrade"
    assert f'exec "{running}" "$@"' in wrapper.read_text(encoding="utf-8")


@pytest.mark.unit
def test_unix_checksum_failure_exits_before_handoff_or_install(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    result = _run(
        tmp_path,
        "--no-launch",
        sums_text=f"{'0' * 64}  FlintTrade-9.9.9-beta.1-linux-x64.AppImage\n",
        extra_env={"FLINTTRADE_UPDATE_HANDOFF": str(handoff)},
    )

    assert result.returncode != 0
    assert "SHA256SUMS.txt did not match the app-verified" in result.stderr
    assert not handoff.exists()
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
def test_unix_dry_run_never_signals_handoff(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    result = _run(
        tmp_path,
        "--dry-run",
        extra_env={"FLINTTRADE_UPDATE_HANDOFF": str(handoff)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not handoff.exists()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_handoff_refuses_to_clobber_an_existing_path(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    handoff.write_text("do not clobber", encoding="utf-8")
    running = _running_appimage(tmp_path)
    parent = subprocess.Popen(["sleep", "5"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "APPIMAGE": str(running),
            },
        )
    finally:
        parent.terminate()
        parent.wait(timeout=5)
    assert result.returncode != 0
    assert handoff.read_text(encoding="utf-8") == "do not clobber"
    assert "new verified installer handoff marker" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_handoff_requires_exact_parent_pid_before_marker(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = _running_appimage(tmp_path)
    result = _run(
        tmp_path,
        "--no-launch",
        extra_env={"FLINTTRADE_UPDATE_HANDOFF": str(handoff), "APPIMAGE": str(running)},
    )
    assert result.returncode != 0
    assert "requires an exact numeric parent PID" in result.stderr
    assert not handoff.exists()
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_handoff_timeout_happens_after_marker_but_before_installed_shell_mutation(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = _running_appimage(tmp_path)
    parent = subprocess.Popen(["sleep", "10"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS": "1",
                "APPIMAGE": str(running),
            },
        )
    finally:
        parent.terminate()
        parent.wait(timeout=5)
    assert result.returncode != 0
    assert "timed out waiting for its exact Electron parent" in result.stderr
    assert handoff.is_file(), "ready marker must precede the bounded parent wait"
    assert running.read_bytes() == b"old Electron shell"
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
def test_unix_linux_handoff_refuses_to_fall_back_without_exact_appimage(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    parent = subprocess.Popen(["sleep", "5"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
            },
        )
    finally:
        parent.terminate()
        parent.wait(timeout=5)

    assert result.returncode != 0
    assert "requires exactly one exact target mode" in result.stderr
    assert not handoff.exists()
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_linux_handoff_stages_direct_appimage_before_marker(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = _running_appimage(tmp_path)
    fake_install = _fake_uname(tmp_path, "Linux", "x86_64") / "install"
    fake_install.write_text("#!/bin/sh\nexit 73\n", encoding="utf-8")
    fake_install.chmod(0o755)
    parent = subprocess.Popen(["sleep", "5"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "APPIMAGE": str(running),
            },
        )
    finally:
        parent.terminate()
        parent.wait(timeout=5)

    assert result.returncode != 0
    assert "stage the verified AppImage" in result.stderr
    assert not handoff.exists()
    assert running.read_bytes() == b"old Electron shell"


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_linux_handoff_forces_managed_extracted_mode(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    extracted_root = tmp_path / ".local" / "opt" / "flinttrade"
    old_app_run = extracted_root / "squashfs-root" / "AppRun"
    old_app_run.parent.mkdir(parents=True)
    old_app_run.write_text("#!/bin/sh\nprintf old-shell\n", encoding="utf-8")
    old_app_run.chmod(0o755)
    appimage = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--appimage-extract" ]; then\n'
        "  mkdir -p squashfs-root\n"
        "  printf '#!/bin/sh\\nprintf new-shell\\n' > squashfs-root/AppRun\n"
        "  chmod 0755 squashfs-root/AppRun\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    ).encode()
    parent = subprocess.Popen(["sleep", "1"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            asset_bytes=appimage,
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "FLINTTRADE_UPDATE_PARENT_TIMEOUT_SECONDS": "5",
                "FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT": str(extracted_root),
            },
        )
    finally:
        parent.wait(timeout=5)

    assert result.returncode == 0, result.stdout + result.stderr
    assert handoff.is_file()
    assert old_app_run.read_text(encoding="utf-8") == "#!/bin/sh\nprintf new-shell\n"
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
def test_unix_linux_handoff_rejects_ambiguous_appimage_and_extracted_targets(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    running = _running_appimage(tmp_path)
    extracted_root = tmp_path / ".local" / "opt" / "flinttrade"
    app_run = extracted_root / "squashfs-root" / "AppRun"
    app_run.parent.mkdir(parents=True)
    app_run.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    app_run.chmod(0o755)
    parent = subprocess.Popen(["sleep", "5"])
    try:
        result = _run(
            tmp_path,
            "--no-launch",
            extra_env={
                "FLINTTRADE_UPDATE_HANDOFF": str(handoff),
                "FLINTTRADE_UPDATE_PARENT_PID": str(parent.pid),
                "APPIMAGE": str(running),
                "FLINTTRADE_UPDATE_LINUX_EXTRACTED_ROOT": str(extracted_root),
            },
        )
    finally:
        parent.terminate()
        parent.wait(timeout=5)

    assert result.returncode != 0
    assert "requires exactly one exact target mode" in result.stderr
    assert not handoff.exists()
    assert running.read_bytes() == b"old Electron shell"
    assert app_run.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_fresh_install_ignores_untrusted_inherited_appimage(tmp_path: Path) -> None:
    running = tmp_path / "custom" / "FlintTrade.AppImage"
    running.parent.mkdir()
    running.write_bytes(b"old shell")
    running.chmod(0o755)
    replacement = b"new Electron shell"
    digest = hashlib.sha256(replacement).hexdigest()
    sums = f"{digest}  FlintTrade-9.9.9-beta.1-linux-x64.AppImage\n"
    result = _run(
        tmp_path,
        "--no-launch",
        asset_bytes=replacement,
        sums_text=sums,
        extra_env={"APPIMAGE": str(running)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert running.read_bytes() == b"old shell"
    installed = tmp_path / ".local" / "bin" / "flinttrade.AppImage"
    assert installed.read_bytes() == replacement
    receipt = tmp_path / ".local" / "state" / "flinttrade" / "shell-install.receipt"
    receipt_text = receipt.read_text(encoding="utf-8")
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert receipt.parent.stat().st_mode & 0o777 == 0o700
    assert "format=flinttrade-electron-shell-v1" in receipt_text
    assert "platform=Linux" in receipt_text
    assert "kind=linux-appimage" in receipt_text
    assert f"target={installed.resolve()}" in receipt_text
    assert f"executable_sha256={hashlib.sha256(replacement).hexdigest()}" in receipt_text


@pytest.mark.unit
def test_unix_appimage_installer_uses_only_the_packaged_flinttrade_icon(tmp_path: Path) -> None:
    canonical = b"canonical FlintTrade icon"
    decoy = b"unrelated bundled PNG"
    appimage = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--appimage-extract" ]; then\n'
        '  [ "${2:-}" = "resources/icons/app.png" ] || exit 72\n'
        "  mkdir -p squashfs-root/resources/icons squashfs-root/usr/share/pixmaps\n"
        f"  printf '%s' {canonical.decode()!r} > squashfs-root/resources/icons/app.png\n"
        f"  printf '%s' {decoy.decode()!r} > squashfs-root/usr/share/pixmaps/decoy.png\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    ).encode()

    result = _run(tmp_path, "--no-launch", asset_bytes=appimage)

    assert result.returncode == 0, result.stdout + result.stderr
    installed_icon = (
        tmp_path
        / ".local"
        / "share"
        / "icons"
        / "hicolor"
        / "128x128"
        / "apps"
        / "flinttrade.png"
    )
    assert installed_icon.read_bytes() == canonical


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_fresh_install_refuses_unproved_existing_appimage_target(tmp_path: Path) -> None:
    target = tmp_path / ".local" / "bin" / "flinttrade.AppImage"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unrelated same-name executable")
    target.chmod(0o755)

    result = _run(tmp_path, "--no-launch")

    assert result.returncode != 0
    assert target.read_bytes() == b"unrelated same-name executable"
    assert "unrelated same-name shell target" in result.stderr
    assert not (tmp_path / ".local" / "state" / "flinttrade" / "shell-install.receipt").exists()


@pytest.mark.unit
def test_unix_fresh_install_refuses_unproved_existing_extracted_target(tmp_path: Path) -> None:
    app_run = tmp_path / ".local" / "opt" / "flinttrade" / "squashfs-root" / "AppRun"
    app_run.parent.mkdir(parents=True)
    app_run.write_text("#!/bin/sh\nprintf unrelated\n", encoding="utf-8")
    app_run.chmod(0o755)
    extracting_appimage = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--appimage-extract" ]; then\n'
        "  mkdir -p squashfs-root\n"
        "  printf '#!/bin/sh\\nprintf new-shell\\n' > squashfs-root/AppRun\n"
        "  chmod 0755 squashfs-root/AppRun\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    ).encode()

    result = _run(tmp_path, "--no-launch", asset_bytes=extracting_appimage)

    assert result.returncode != 0
    assert app_run.read_text(encoding="utf-8") == "#!/bin/sh\nprintf unrelated\n"
    assert "unrelated same-name shell target" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative_collision",
    (
        Path(".local/bin/flinttrade"),
        Path(".local/share/applications/flinttrade.desktop"),
        Path(".local/share/icons/hicolor/128x128/apps/flinttrade.png"),
    ),
)
def test_unix_fresh_install_refuses_symlinked_integration_leaf(
    tmp_path: Path,
    relative_collision: Path,
) -> None:
    victim = tmp_path / "unrelated-user-file"
    victim.write_text("keep", encoding="utf-8")
    collision = tmp_path / relative_collision
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.symlink_to(victim)

    result = _run(tmp_path, "--no-launch")

    assert result.returncode != 0
    assert collision.is_symlink()
    assert victim.read_text(encoding="utf-8") == "keep"
    assert "non-ordinary installer integration path" in result.stderr
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()


@pytest.mark.unit
@pytest.mark.parametrize("failed_publication", ["desktop", "receipt"])
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_install_publication_failure_rolls_back_shell_and_integrations(
    tmp_path: Path,
    failed_publication: str,
) -> None:
    bin_dir = _fake_uname(tmp_path, "Linux", "x86_64")
    fake_mv = bin_dir / "mv"
    match = (
        '*/.flinttrade-integration.*:*flinttrade.desktop) exit 73 ;;'
        if failed_publication == "desktop"
        else '*/.shell-install.receipt.*:*shell-install.receipt) exit 73 ;;'
    )
    fake_mv.write_text(
        "#!/bin/sh\n"
        'last=""\n'
        'for argument in "$@"; do last="$argument"; done\n'
        f'case "$1:$last" in {match} esac\n'
        'exec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)

    result = _run(tmp_path, "--no-launch")

    assert result.returncode != 0
    assert "Could not publish the installer-owned file" in result.stderr
    assert not (tmp_path / ".local" / "bin" / "flinttrade.AppImage").exists()
    assert not (tmp_path / ".local" / "bin" / "flinttrade").exists()
    assert not (tmp_path / ".local" / "share" / "applications" / "flinttrade.desktop").exists()
    assert not (tmp_path / ".local" / "state" / "flinttrade" / "shell-install.receipt").exists()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_signal_after_preserving_target_restores_the_journalled_backup(tmp_path: Path) -> None:
    installed = tmp_path / ".local" / "bin" / "flinttrade.AppImage"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"old Electron shell")
    installed.chmod(0o755)
    wrapper, desktop = _plant_linux_integrations(tmp_path, installed)
    original_wrapper = wrapper.read_bytes()
    original_desktop = desktop.read_bytes()

    fake_mv = _fake_uname(tmp_path, "Linux", "x86_64") / "mv"
    fake_mv.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = {str(installed)!r} ]; then\n'
        '  /bin/mv "$@"\n'
        '  kill -TERM "$PPID"\n'
        "  sleep 1\n"
        "  exit 0\n"
        "fi\n"
        'exec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)

    result = _run(tmp_path, "--no-launch")

    assert result.returncode == 143, result.stdout + result.stderr
    assert installed.read_bytes() == b"old Electron shell"
    assert wrapper.read_bytes() == original_wrapper
    assert desktop.read_bytes() == original_desktop
    assert not list(installed.parent.glob(".flinttrade-rollback.*"))


@pytest.mark.unit
def test_unix_directory_shell_replacements_are_staged_and_rollback_capable() -> None:
    text = SH.read_text(encoding="utf-8")
    mac = text[text.index("install_macos_dmg()") : text.index("linux_fuse_available()")]
    extracted = text[text.index("install_linux_appimage_extracted()") : text.index("install_linux_appimage()")]

    assert mac.index('ditto "$app_path" "$staged_app"') < mac.index("signal_update_handoff")
    assert mac.index("signal_update_handoff") < mac.index("replace_directory_transactionally")
    assert 'rm -rf "$dest/FlintTrade.app"' not in mac
    assert "Contents/Info.plist" in mac and "Contents/MacOS/FlintTrade" in mac
    assert "FLINTTRADE_UPDATE_MACOS_APP_BUNDLE" in mac
    assert "AppTranslocation" in mac
    assert '"$target_app" = "$requested_target"' in mac
    assert 'open "$target_app"' in mac
    assert extracted.index('"$appimage" --appimage-extract') < extracted.index("signal_update_handoff")
    assert extracted.index("signal_update_handoff") < extracted.index("replace_directory_transactionally")
    assert 'rm -rf "$opt_dir"' not in extracted
    assert 'mv "$ACTIVE_SWAP_BACKUP" "$ACTIVE_SWAP_TARGET"' in text
    assert "restore_interrupted_swap" in text
    direct = text[text.index('local staged icon_tmp icon wrapper="$dest_bin/flinttrade"') : text.index("install_binary_release()")]
    assert direct.index('install -m 0755 "$appimage" "$staged"') < direct.index("signal_update_handoff")
    assert direct.index("signal_update_handoff") < direct.index('publish_file_transactionally "$staged" "$dest"')
    for installer in (mac, extracted, direct):
        assert installer.index("begin_install_transaction") < installer.index("write_shell_receipt")
        assert installer.index("write_shell_receipt") < installer.index("commit_install_transaction")
    publication = text[text.index("publish_file_transactionally()") : text.index("commit_install_transaction()")]
    assert publication.index("INSTALL_TRANSACTION_HAD_PREVIOUS") < publication.index(
        "restore_install_signal_traps"
    )
    assert publication.index("restore_install_signal_traps") < publication.index(
        'deferred_signal="$DEFERRED_INSTALL_SIGNAL"'
    )


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_unix_extracted_shell_swap_failure_restores_previous_install(tmp_path: Path) -> None:
    old_app_run = tmp_path / ".local" / "opt" / "flinttrade" / "squashfs-root" / "AppRun"
    old_app_run.parent.mkdir(parents=True)
    old_app_run.write_text("#!/bin/sh\nprintf old-shell\n", encoding="utf-8")
    old_app_run.chmod(0o755)
    _plant_linux_integrations(tmp_path, old_app_run)
    appimage = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--appimage-extract" ]; then\n'
        "  mkdir -p squashfs-root\n"
        "  printf '#!/bin/sh\\nprintf new-shell\\n' > squashfs-root/AppRun\n"
        "  chmod 0755 squashfs-root/AppRun\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    ).encode()
    fake_mv = _fake_uname(tmp_path, "Linux", "x86_64") / "mv"
    fake_mv.write_text(
        "#!/bin/sh\n"
        'case "$1" in */new) exit 73 ;; esac\n'
        'exec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)

    result = _run(tmp_path, "--no-launch", asset_bytes=appimage)

    assert result.returncode != 0
    assert "restored the previous installed shell" in result.stderr
    assert old_app_run.read_text(encoding="utf-8") == "#!/bin/sh\nprintf old-shell\n"


@pytest.mark.unit
def test_unix_interrupted_directory_swap_restores_previous_install(tmp_path: Path) -> None:
    old_app_run = tmp_path / ".local" / "opt" / "flinttrade" / "squashfs-root" / "AppRun"
    old_app_run.parent.mkdir(parents=True)
    old_app_run.write_text("#!/bin/sh\nprintf old-shell\n", encoding="utf-8")
    old_app_run.chmod(0o755)
    _plant_linux_integrations(tmp_path, old_app_run)
    appimage = (
        "#!/bin/sh\n"
        'if [ "${1:-}" = "--appimage-extract" ]; then\n'
        "  mkdir -p squashfs-root\n"
        "  printf '#!/bin/sh\\nprintf new-shell\\n' > squashfs-root/AppRun\n"
        "  chmod 0755 squashfs-root/AppRun\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    ).encode()
    fake_mv = _fake_uname(tmp_path, "Linux", "x86_64") / "mv"
    fake_mv.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        '  */new) kill -TERM "$PPID"; sleep 1; exit 143 ;;\n'
        "esac\n"
        'exec /bin/mv "$@"\n',
        encoding="utf-8",
    )
    fake_mv.chmod(0o755)

    result = _run(tmp_path, "--no-launch", asset_bytes=appimage)

    assert result.returncode != 0
    assert old_app_run.read_text(encoding="utf-8") == "#!/bin/sh\nprintf old-shell\n"
    assert not list((tmp_path / ".local" / "opt").glob(".flinttrade-install.*"))


@pytest.mark.unit
@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="would target the real writable /Applications on macOS",
)
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_INSTALL_REASON)
def test_macos_dmg_installs_after_same_release_verification(tmp_path: Path) -> None:
    bin_dir = _fake_uname(tmp_path, "Darwin", "arm64")
    (bin_dir / "hdiutil").write_text(
        "#!/bin/sh\n"
        'verb="$1"; shift\n'
        'if [ "$verb" = "attach" ]; then\n'
        '  mp=""\n'
        '  while [ $# -gt 0 ]; do [ "$1" = "-mountpoint" ] && { mp="$2"; shift; }; shift; done\n'
        '  head -c1 >/dev/null 2>&1 || true\n'
        '  mkdir -p "$mp/FlintTrade.app/Contents/MacOS"\n'
        '  printf plist > "$mp/FlintTrade.app/Contents/Info.plist"\n'
        '  printf marker > "$mp/FlintTrade.app/Contents/MacOS/FlintTrade"\n'
        '  chmod 0755 "$mp/FlintTrade.app/Contents/MacOS/FlintTrade"\n'
        "fi\n"
        "exit 0\n"
    )
    (bin_dir / "hdiutil").chmod(0o755)
    (bin_dir / "ditto").write_text('#!/bin/sh\ncp -R "$1" "$2"\n')
    (bin_dir / "ditto").chmod(0o755)
    (bin_dir / "open").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "open").chmod(0o755)
    result = _run(tmp_path, "--no-launch", os_name="Darwin", machine="arm64")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verified SHA-256 checksum" in result.stdout
    assert (tmp_path / "Applications" / "FlintTrade.app" / "Contents" / "MacOS" / "FlintTrade").is_file()


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_SHELL_REASON)
def test_source_build_is_electron_only_and_refuses_foreign_existing_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "remote", "add", "origin", "https://evil.invalid/FlintTrade.git"],
        check=True,
    )
    result = subprocess.run(
        ["bash", str(SH), "--build-from-source", "--dry-run", "--src", str(checkout)],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "origin is not the official HTTPS" in result.stderr


@pytest.mark.unit
@pytest.mark.skipif(not POSIX_INSTALL_SEMANTICS, reason=NO_POSIX_SHELL_REASON)
def test_source_build_refuses_managed_active_checkout(tmp_path: Path) -> None:
    managed = tmp_path / ".flinttrade" / "src" / "FlintTrade"
    result = subprocess.run(
        ["bash", str(SH), "--build-from-source", "--dry-run", "--src", str(managed)],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "refuses to mutate the managed active source tree" in result.stderr


@pytest.mark.unit
def test_source_build_tag_resolution_prefers_stable_at_equal_version(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SH)],
        input="v9.9.8\nv9.9.9-beta.1\nv9.9.9-rc.2\nv9.9.9\n",
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
    assert result.stdout.strip() == "v9.9.9"


@pytest.mark.unit
def test_source_build_default_beta_channel_excludes_newer_alpha_and_rc_tags(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SH)],
        input="v10.0.0-alpha.1\nv9.9.9-rc.1\nv9.9.9-beta.10\nv9.9.9-beta.9\n",
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
    assert result.stdout.strip() == "v9.9.9-beta.10"


@pytest.mark.unit
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX FIFO regression")
def test_posix_successful_detached_update_preserves_a_fifo_swapped_stage_path(tmp_path: Path) -> None:
    staging_root = tmp_path / "private" / "shell-updates" / "staging"
    stage = staging_root / "flinttrade-shell-update-running"
    captured_stage = staging_root / "flinttrade-shell-update-captured"
    stage.mkdir(parents=True, mode=0o700)
    staging_root.chmod(0o700)
    stage.chmod(0o700)
    staged_script = stage / SH.name
    shutil.copy2(SH, staged_script)
    staged_script.chmod(0o700)
    fifo = tmp_path / "release-tags.fifo"
    os.mkfifo(fifo, mode=0o600)
    started = tmp_path / "installer-started"
    bash_env = tmp_path / "bash-env.sh"
    bash_env.write_text('printf started > "$FLINTTRADE_TEST_STARTED"\n', encoding="utf-8")

    anchor_fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    read_fd = os.open(fifo, os.O_RDONLY)
    write_fd = os.open(fifo, os.O_WRONLY)
    os.close(anchor_fd)
    process: subprocess.Popen[str] | None = None
    try:
        with os.fdopen(read_fd, "r", encoding="utf-8") as read_stream:
            process = subprocess.Popen(
                ["bash", str(staged_script)],
                cwd=ROOT,
                env={
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": str(tmp_path),
                    "BASH_ENV": str(bash_env),
                    "FLINTTRADE_TEST_STARTED": str(started),
                    "FLINTTRADE_RESOLVE_TAGS_ONLY": "1",
                    # These recreate the old vulnerable cleanup inputs. They
                    # are now ignored, so a swapped pathname is preserved.
                    "FLINTTRADE_UPDATE_HANDOFF": str(tmp_path / "handoff"),
                    "FLINTTRADE_UPDATE_STAGE_DIR": str(stage.resolve()),
                    "FLINTTRADE_UPDATE_STAGE_ROOT": str(staging_root.resolve()),
                },
                stdin=read_stream,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        deadline = time.monotonic() + 5
        while not started.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "staged installer did not reach its FIFO read boundary"

        stage.rename(captured_stage)
        stage.mkdir(mode=0o700)
        replacement_script = stage / SH.name
        shutil.copy2(SH, replacement_script)
        replacement_script.chmod(0o700)
        sentinel = stage / "foreign-sentinel"
        sentinel.write_text("preserve me", encoding="utf-8")

        with os.fdopen(write_fd, "w", encoding="utf-8") as writer:
            writer.write("v9.9.9-beta.9\nv9.9.9-beta.10\n")
        write_fd = -1
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0, stdout + stderr
    assert stdout.strip() == "v9.9.9-beta.10"
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert replacement_script.is_file()
    assert captured_stage.is_dir()


@pytest.mark.unit
def test_detached_installers_never_recursively_remove_their_staging_path() -> None:
    unix = SH.read_text(encoding="utf-8")
    windows = PS1.read_text(encoding="utf-8")

    assert "FLINTTRADE_UPDATE_STAGE_DIR" not in unix
    assert "FLINTTRADE_UPDATE_STAGE_ROOT" not in unix
    assert "remove_verified_update_stage" not in unix
    assert "FLINTTRADE_UPDATE_STAGE_DIR" not in windows
    assert "FLINTTRADE_UPDATE_STAGE_ROOT" not in windows
    assert "Remove-VerifiedUpdateStage" not in windows


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL or sys.platform != "win32", reason=NO_POWERSHELL_REASON)
def test_windows_successful_detached_update_preserves_a_swapped_stage_path(tmp_path: Path) -> None:
    staging_root = tmp_path / "private" / "shell-updates" / "staging"
    stage = staging_root / "flinttrade-shell-update-running"
    captured_stage = staging_root / "flinttrade-shell-update-captured"
    stage.mkdir(parents=True)
    staged_script = stage / PS1.name
    started = tmp_path / "installer-started"
    injected = PS1.read_text(encoding="utf-8").replace(
        '$ProgressPreference = "SilentlyContinue"',
        '$ProgressPreference = "SilentlyContinue"\n'
        '[System.IO.File]::WriteAllText($env:FLINTTRADE_TEST_STARTED, "started")',
        1,
    )
    staged_script.write_text(injected, encoding="utf-8")

    process = subprocess.Popen(
        [POWERSHELL, "-NoProfile", "-File", str(staged_script)],
        cwd=ROOT,
        env={
            **os.environ,
            "FLINTTRADE_TEST_STARTED": str(started),
            "FLINTTRADE_RESOLVE_TAGS_ONLY": "1",
            "FLINTTRADE_UPDATE_HANDOFF": str(tmp_path / "handoff"),
            "FLINTTRADE_UPDATE_STAGE_DIR": str(stage.resolve()),
            "FLINTTRADE_UPDATE_STAGE_ROOT": str(staging_root.resolve()),
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while not started.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists(), "staged PowerShell installer did not reach its stdin boundary"

    stage.rename(captured_stage)
    stage.mkdir()
    replacement_script = stage / PS1.name
    shutil.copy2(PS1, replacement_script)
    sentinel = stage / "foreign-sentinel"
    sentinel.write_text("preserve me", encoding="utf-8")
    stdout, stderr = process.communicate("v9.9.9-beta.9\nv9.9.9-beta.10\n", timeout=20)

    assert process.returncode == 0, stdout + stderr
    assert stdout.strip() == "v9.9.9-beta.10"
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert replacement_script.is_file()
    assert captured_stage.is_dir()


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_source_tag_resolution_orders_multidigit_prerelease_identifiers(tmp_path: Path) -> None:
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(PS1)],
        input="v9.9.9-beta.9\nv9.9.9-beta.10\n",
        cwd=ROOT,
        env={**os.environ, "FLINTTRADE_RESOLVE_TAGS_ONLY": "1", "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "v9.9.9-beta.10"


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_installer_parses_when_powershell_is_available() -> None:
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


@pytest.mark.unit
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_dry_run_selects_exact_nsis_and_same_release_sums(tmp_path: Path) -> None:
    script_path = str(PS1).replace("'", "''")
    harness = tmp_path / "windows-installer-harness.ps1"
    harness.write_text(
        f"""
function Get-CimInstance {{ [pscustomobject]@{{ Architecture = 9 }} }}
function Get-ItemProperty {{
    param($Path, $ErrorAction)
    return $null
}}
function Invoke-RestMethod {{
    param($Uri, $Headers)
    Write-Host "API-URL: $Uri"
    [pscustomobject]@{{
        tag_name = "v9.9.9-beta.1"
        draft = $false
        prerelease = $true
        assets = @(
            [pscustomobject]@{{ name = "FlintTrade-9.9.9-beta.1-win-x64.exe"; browser_download_url = "{RELEASE_DOWNLOAD_BASE}/v9.9.9-beta.1/FlintTrade-9.9.9-beta.1-win-x64.exe" }},
            [pscustomobject]@{{ name = "SHA256SUMS.txt"; browser_download_url = "{RELEASE_DOWNLOAD_BASE}/v9.9.9-beta.1/SHA256SUMS.txt" }}
        )
    }}
}}
function Invoke-WebRequest {{
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    Set-Content -LiteralPath $OutFile -NoNewline -Value "{('0' * 64)}  FlintTrade-9.9.9-beta.1-win-x64.exe`n"
}}
& '{script_path}' -Ref v9.9.9-beta.1 -Yes -DryRun -NoLaunch
""".strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(harness)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"API-URL: {GITHUB_API_BASE}/releases/tags/v9.9.9-beta.1" in result.stdout
    assert "would download FlintTrade-9.9.9-beta.1-win-x64.exe" in result.stdout
    assert f"{RELEASE_DOWNLOAD_BASE}/v9.9.9-beta.1/SHA256SUMS.txt" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize(
    ("channel", "newest_version", "selected_version", "prerelease_literal"),
    [
        ("stable", "10.0.1", "10.0.0", "$false"),
        ("beta", "10.0.0-beta.2", "10.0.0-beta.1", "$true"),
    ],
)
@pytest.mark.skipif(not POWERSHELL, reason=NO_POWERSHELL_REASON)
def test_windows_channel_skips_incomplete_newest_release(
    tmp_path: Path,
    channel: str,
    newest_version: str,
    selected_version: str,
    prerelease_literal: str,
) -> None:
    script_path = str(PS1).replace("'", "''")
    harness = tmp_path / "windows-release-fallback-harness.ps1"
    harness.write_text(
        f"""
function Get-CimInstance {{ [pscustomobject]@{{ Architecture = 9 }} }}
function Invoke-RestMethod {{
    param($Uri, $Headers)
    Write-Host "API-URL: $Uri"
    $newest = [pscustomobject]@{{
        tag_name = "v{newest_version}"
        draft = $false
        prerelease = {prerelease_literal}
        assets = @(
            [pscustomobject]@{{ name = "SHA256SUMS.txt"; browser_download_url = "https://evil.invalid/SHA256SUMS.txt" }}
        )
    }}
    $selected = [pscustomobject]@{{
        tag_name = "v{selected_version}"
        draft = $false
        prerelease = {prerelease_literal}
        assets = @(
            [pscustomobject]@{{ name = "FlintTrade-{selected_version}-win-x64.exe"; browser_download_url = "{RELEASE_DOWNLOAD_BASE}/v{selected_version}/FlintTrade-{selected_version}-win-x64.exe" }},
            [pscustomobject]@{{ name = "SHA256SUMS.txt"; browser_download_url = "{RELEASE_DOWNLOAD_BASE}/v{selected_version}/SHA256SUMS.txt" }}
        )
    }}
    @($newest, $selected)
}}
function Invoke-WebRequest {{
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    Set-Content -LiteralPath $OutFile -NoNewline -Value "{('0' * 64)}  FlintTrade-{selected_version}-win-x64.exe`n"
}}
& '{script_path}' -Channel {channel} -DryRun -NoLaunch
""".strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(harness)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"API-URL: {GITHUB_API_BASE}/releases?per_page=100" in result.stdout
    assert f"FlintTrade-{selected_version}-win-x64.exe" in result.stdout
    assert newest_version not in result.stdout


@pytest.mark.unit
def test_windows_handoff_occurs_only_after_hash_verification_and_before_setup() -> None:
    text = PS1.read_text(encoding="utf-8")
    function = text[text.index("function Install-BinaryRelease") : text.index("function Assert-TrustedSourceOrigin")]
    checksum = function.index("$actualHash -ne $expectedHash")
    marker = function.index("Signal-UpdateHandoff")
    setup = function.index('Say "Running FlintTrade setup..."')
    assert checksum < marker < setup
    binding = function.index("$expectedHash -cne $attestedHash")
    assert binding < checksum < marker
    assert "FLINTTRADE_UPDATE_ASSET_NAME" in function
    assert "FLINTTRADE_UPDATE_ASSET_SHA256" in function
    assert "$script:UpdateAttestationBound = $true" in function
    assert "[switch]$Update" in text
    handoff = text[text.index("function Signal-UpdateHandoff") : text.index("function Install-BinaryRelease")]
    assert "FLINTTRADE_UPDATE_PARENT_PID" in handoff
    assert "requires explicit -Update mode" in handoff
    assert "app-verified release attestation binding" in handoff
    assert "StartTime.ToFileTimeUtc()" in handoff
    assert "$timeout = 3600" in handoff
    assert "$activeWaitIterations = $timeout * 5" in handoff
    assert "UtcNow.AddSeconds" not in handoff
    assert "timed out waiting for its exact Electron parent" in handoff
    assert '"--force-run"' in text
    assert '"/D=$script:WindowsUpdateInstallDir"' in text
    assert text.index('"--force-run"') < text.index('"/D=$script:WindowsUpdateInstallDir"')
    assert "Assert-WindowsUpdateTarget" in text
    assert "DisplayIcon" in text and "InstallLocation" in text
    assert "Assert-WindowsFreshInstallAdmission" in text
    assert "[Environment+SpecialFolder]::LocalApplicationData" in text
    assert r'Join-Path $LocalAppDataRoot "Programs\FlintTrade"' in text
    fresh_admission = text[
        text.index("function Get-ProvenDefaultElectronRegistryEntry") : text.index("function Assert-WindowsUpdateTarget")
    ]
    assert '"Uninstall FlintTrade.exe"' in fresh_admission
    assert "Test-WindowsPathContainsReparsePoint" in fresh_admission
    assert "$uninstallerItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint" in fresh_admission
    assert "$executableItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint" in fresh_admission
    assert "unproven same-name FlintTrade registry identity" in fresh_admission
    assert "default Electron install directory exists without one exact registered FlintTrade identity" in fresh_admission
    update_proof = text[
        text.index("function Assert-WindowsUpdateTarget") : text.index("function Assert-VerifiedLegacyShell")
    ]
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" in update_proof
    assert "HKLM:" not in update_proof
    assert "$entries.Count -ne 1" in update_proof and "$records.Count -ne 1" in update_proof
    assert "Get-ProvenDefaultElectronRegistryEntry" in update_proof
    assert "Test-WindowsPathContainsReparsePoint $canonical" in update_proof
    assert "canonical, ordinary per-user Electron install directory" in update_proof
    assert '"uninstall.exe"' not in update_proof
    assert "-beta(?:\\.|\\+|$)" in text
    assert ".flinttrade\\source-build\\FlintTrade" in text
    assert "Assert-IsolatedSourceBuildTarget" in text
    assert "Resolve-LatestReleaseTag" in text and "Compare-FlintSemVer" in text
    assert "Test-ReleaseTagForChannel" in text
    assert 'Join-Path $LocalAppDataRoot "FlintTrade"' in text
    assert "Remove-VerifiedLegacyShell" in text
    assert "legacy desktop shell" in text
    assert 'Join-Path $LegacyShellInstallDir "uninstall.exe"' in text
    assert 'Join-Path $env:LOCALAPPDATA $LegacyBundleId' not in text
    binary_install = text[text.index("function Install-BinaryRelease") : text.index("function Assert-TrustedSourceOrigin")]
    assert binary_install.index("Assert-VerifiedLegacyShell") < binary_install.index("Signal-UpdateHandoff")
    assert binary_install.index("Assert-WindowsFreshInstallAdmission") < binary_install.index("Get-SelectedRelease")
    assert binary_install.rindex("Assert-WindowsFreshInstallAdmission") < binary_install.index("Signal-UpdateHandoff")
    assert binary_install.index("$setup.ExitCode -ne 0") < binary_install.index("Remove-VerifiedLegacyShell")
    source_install = text[text.index("function Build-FromSource") : text.index("if ($env:FLINTTRADE_RESOLVE_TAGS_ONLY")]
    assert source_install.index("Assert-VerifiedLegacyShell") < source_install.index("Start-Process -FilePath $installer")
    assert source_install.index("Assert-WindowsFreshInstallAdmission") < source_install.index("if ($DryRun)")
    assert source_install.rindex("Assert-WindowsFreshInstallAdmission") < source_install.index(
        "Start-Process -FilePath $installer"
    )
    assert source_install.index("$setup.ExitCode -ne 0") < source_install.index("Remove-VerifiedLegacyShell")
    legacy_retirement = text[
        text.index("function Remove-VerifiedLegacyShell") : text.index("function Signal-UpdateHandoff")
    ]
    assert "Start-Process" not in legacy_retirement
    assert "Remove-Item -LiteralPath $verified.Directory" in legacy_retirement
    assert "$currentEntry.UninstallString" in legacy_retirement
