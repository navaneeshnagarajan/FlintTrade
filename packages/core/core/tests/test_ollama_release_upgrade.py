"""Published release selection and inert previous-install compatibility."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from flinttrade_core import ollama_runtime
from flinttrade_core.ollama_runtime import OllamaAsset, OllamaRuntime, OllamaRuntimeError


@pytest.mark.parametrize(
    "system,machine,accelerator",
    [
        ("Darwin", "arm64", ""),
        ("Darwin", "x86_64", ""),
        ("Linux", "x86_64", ""),
        ("Linux", "arm64", ""),
        ("Windows", "AMD64", ""),
        ("Windows", "arm64", ""),
        ("Linux", "x86_64", "rocm"),
        ("Linux", "arm64", "jetpack5"),
        ("Linux", "arm64", "jetpack6"),
    ],
)
def test_default_assets_match_the_published_release(system, machine, accelerator) -> None:
    release = json.loads((Path(__file__).parent / "fixtures" / "ollama-v0.40.4-release.json").read_text())
    published = {asset["name"]: asset for asset in release["assets"]}
    assert release["tag_name"] == "v0.40.4"
    assert release["draft"] is False and release["prerelease"] is False
    assets = ollama_runtime._assets_for_platform(system=system, machine=machine, accelerator=accelerator)
    for asset in assets:
        expected = published[asset.name]
        assert asset.url == expected["browser_download_url"]
        assert asset.sha256 == expected["digest"].removeprefix("sha256:")
        assert asset.size_bytes == expected["size"]
        assert asset.max_extracted_bytes > 0
    assert len(assets) == (2 if accelerator else 1)


def test_new_default_keeps_every_previously_trusted_release(tmp_path: Path) -> None:
    runtime = OllamaRuntime(tmp_path)
    assert runtime.target_version == "v0.40.4"
    assert set(runtime._release_assets) == {"v0.40.4", "v0.35.0", "v0.32.0", "v0.31.2"}
    previous = ollama_runtime._asset_for_platform(system="Linux", machine="x86_64", version="v0.35.0")
    assert previous.sha256 == "1c114a6b220c5efca2ef2b1e5f01d1e535e26f6cd6d1678c8489325d2835e525"
    assert previous.size_bytes == 1_427_765_407
    assert previous.max_extracted_bytes == 6 * 1024 * 1024 * 1024
    assert not runtime.status()["installed"]


@pytest.mark.parametrize("corrupt_target", [False, True])
def test_new_default_preserves_previous_install_until_explicit_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corrupt_target: bool,
) -> None:
    """Run the real state/install/update/rollback path with tiny inert ZIPs."""
    archives = {}
    assets = {}
    downloads = []
    for version in ("v0.31.2", "v0.32.0", "v0.35.0", "v0.40.4"):
        archive = tmp_path / f"ollama-{version}.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("bin/ollama", version.encode())
        archives[archive.name] = archive
        assets[version] = (
            OllamaAsset(
                name=archive.name,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                url=f"https://downloads.example.invalid/{archive.name}",
                size_bytes=archive.stat().st_size,
                max_extracted_bytes=1024,
            ),
        )
    monkeypatch.setattr(ollama_runtime, "_assets_for_platform", lambda *, version: assets[version])

    def download(asset, destination, progress):
        downloads.append(asset.name)
        payload = archives[asset.name].read_bytes()
        if corrupt_target and "v0.40.4" in asset.name:
            payload += b"corrupt"
        destination.write_bytes(payload)
        progress(len(payload), len(payload))

    workspace = tmp_path / "workspace"
    old = OllamaRuntime(workspace, target_version="v0.35.0", downloader=download)
    old.install()
    original_state = old._runtime_state_path().read_bytes()
    executable = old.install_dir / "bin" / "ollama"
    old_bytes = executable.read_bytes()
    old_identity = (executable.stat().st_ino, executable.stat().st_mtime_ns)
    before_downloads = list(downloads)
    current = OllamaRuntime(workspace, downloader=download)
    status = current.status()
    assert status["target_version"] == "v0.40.4"
    assert status["active_version"] == "v0.35.0"
    assert status["installed"] is True and status["update_available"] is True
    assert downloads == before_downloads
    assert current._runtime_state_path().read_bytes() == original_state
    if corrupt_target:
        with pytest.raises(OllamaRuntimeError, match="hash verification failed"):
            current.update()
        assert current._runtime_state_path().read_bytes() == original_state
        assert not (current.runtime_root / "v0.40.4").exists()
    else:
        updated = current.update()
        assert updated["active_version"] == "v0.40.4"
        assert updated["previous_version"] == "v0.35.0"
        assert updated["rollback_available"] is True
        assert (current.install_dir / "bin" / "ollama").read_bytes() == b"v0.40.4"
        rolled_back = current.rollback()
        assert rolled_back["active_version"] == "v0.35.0"
        assert rolled_back["previous_version"] == "v0.40.4"
        reopened = OllamaRuntime(workspace, downloader=download)
        assert reopened.status()["active_version"] == "v0.35.0"
    assert executable.read_bytes() == old_bytes
    assert (executable.stat().st_ino, executable.stat().st_mtime_ns) == old_identity
    assert not current.models_dir.exists()
