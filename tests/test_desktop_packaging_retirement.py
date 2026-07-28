"""Focused guards for the Electron-owned desktop packaging surface."""

from __future__ import annotations

import json
import runpy
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "packages" / "apps" / "desktop"


def test_electron_owns_desktop_icons_and_packaged_tray_resource() -> None:
    metadata = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    icons = DESKTOP / "resources" / "icons"

    assert {path.name for path in icons.iterdir()} == {
        "128x128.png",
        "128x128@2x.png",
        "32x32.png",
        "icon.icns",
        "icon.ico",
        "icon.png",
    }
    assert all(path.is_file() and path.stat().st_size > 0 for path in icons.iterdir())
    assert metadata["build"]["icon"] == "resources/icons/icon"
    assert metadata["build"]["mac"]["icon"] == "resources/icons/icon.icns"
    assert metadata["build"]["win"]["icon"] == "resources/icons/icon.ico"
    assert metadata["build"]["linux"]["icon"] == "resources/icons/icon.png"
    assert {
        metadata["build"]["nsis"][key]
        for key in ("installerIcon", "uninstallerIcon", "installerHeaderIcon")
    } == {"resources/icons/icon.ico"}
    assert {
        (resource["from"], resource["to"])
        for resource in metadata["build"]["extraResources"]
        if resource.get("to") == "icons/tray.png"
    } == {("resources/icons/32x32.png", "icons/tray.png")}
    assert {
        (resource["from"], resource["to"])
        for resource in metadata["build"]["extraResources"]
        if resource.get("to") == "icons/app.png"
    } == {("resources/icons/128x128.png", "icons/app.png")}

    verifier = (DESKTOP / "scripts" / "verify-electron-package.mjs").read_text(encoding="utf-8")
    main = (DESKTOP / "electron" / "main.ts").read_text(encoding="utf-8")
    generator = (ROOT / "packaging" / "make-icons.py").read_text(encoding="utf-8")
    assert 'path.join(packageRoot, "resources", "icons", "32x32.png")' in verifier
    assert 'path.join(packageRoot, "resources", "icons", "128x128.png")' in verifier
    assert 'path.join(appRoot, "resources", "icons", "32x32.png")' in main
    assert 'path.join(appRoot, "resources", "icons", "128x128.png")' in main
    assert '"desktop" / "resources" / "icons"' in generator


def test_desktop_icon_generator_uses_the_canonical_flinttrade_mark(tmp_path: Path) -> None:
    generator = runpy.run_path(str(ROOT / "packaging" / "make-icons.py"))
    master = generator["render_master"]()

    assert master.size == (1024, 1024)
    assert master.mode == "RGBA"
    assert master.getpixel((40, 40)) == (0, 0, 0, 0)

    mark = generator["MARK"]
    spark = generator["SPARK"]
    spark_highlight = generator["SPARK_HIGHLIGHT"]
    background = generator["BG"]

    # Canonical angular F letterform.
    assert master.getpixel((224, 720)) == mark
    assert master.getpixel((480, 240)) == mark
    assert master.getpixel((440, 496)) == mark

    # Canonical green flint spark and fixed dark app tile.
    assert master.getpixel((704, 272)) == spark
    assert master.getpixel((760, 176)) == spark_highlight
    assert master.getpixel((560, 720)) == background

    # The retired generic orange diamond must not return.
    assert generator.get("ACCENT") is None
    assert generator.get("ACCENT_2") is None

    generated = generator["write_icons"](tmp_path)
    tracked_icons = DESKTOP / "resources" / "icons"
    assert {path.name for path in generated} == {path.name for path in tracked_icons.iterdir()}
    for path in generated:
        assert path.read_bytes() == (tracked_icons / path.name).read_bytes()


def test_retired_desktop_packaging_cannot_return_through_active_manifests() -> None:
    retired_paths = (
        DESKTOP / "src-tauri",
        ROOT / "packaging" / "build-backend.sh",
        ROOT / "packaging" / "flinttrade-backend.spec",
        ROOT / "scripts" / "package" / "create-macos-dmg.sh",
        ROOT / "supply-chain" / "vendor" / "plist-1.9.0",
    )
    assert [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()] == []

    metadata_text = (DESKTOP / "package.json").read_text(encoding="utf-8")
    desktop_ignore = (DESKTOP / ".gitignore").read_text(encoding="utf-8")
    icon_generator = (ROOT / "packaging" / "make-icons.py").read_text(encoding="utf-8")
    for token in ("@tauri-apps", "src-tauri", "pyinstaller", "flinttrade-payload"):
        assert token not in metadata_text.lower()
        assert token not in desktop_ignore.lower()
        assert token not in icon_generator.lower()

    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert "@tauri-apps" not in lock


def test_python_source_backend_entrypoint_survives_without_freezer_extra() -> None:
    pyproject_path = ROOT / "packages" / "core" / "core" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["flinttrade-desktop-backend"] == "flinttrade_core.desktop:main"
    assert "desktop" not in pyproject["project"]["optional-dependencies"]
    assert "pyinstaller" not in (ROOT / "uv.lock").read_text(encoding="utf-8").lower()


def test_rust_audit_and_broker_licence_policy_match_the_electron_cutover() -> None:
    cargo_allowlist = yaml.safe_load(
        (ROOT / "supply-chain" / "cargo-audit-allowlist.yml").read_text(encoding="utf-8"),
    )
    cargo_script = (ROOT / "scripts" / "cargo-audit-with-allowlist.py").read_text(encoding="utf-8")
    licence_policy = (ROOT / "supply-chain" / "licence-allowlist.yml").read_text(encoding="utf-8")

    assert cargo_allowlist == {"allowlist": []}
    assert "tauri" not in cargo_script.lower()
    assert "tauri" not in licence_policy.lower()
    assert "pyinstaller" not in licence_policy.lower()
    assert "EXCLUDED from published desktop shell installers" in licence_policy
    assert "operator-directed source bootstrap installs it locally" in licence_policy
    assert "LicenseRef-operator-cleared-broker-sdk" in licence_policy


def test_hermes_attribution_remains_in_the_electron_package_contract() -> None:
    metadata = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    resources = {(entry["from"], entry["to"]) for entry in metadata["build"]["extraResources"]}

    assert ("resources/licenses/hermes-agent-LICENSE", "licenses/hermes-agent-LICENSE") in resources
    assert (DESKTOP / "resources" / "licenses" / "hermes-agent-LICENSE").is_file()
    assert "hermes-agent" in (ROOT / "notice").read_text(encoding="utf-8").lower()
