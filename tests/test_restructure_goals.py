"""Regression checks for the v0.6.0 restructure repository shape."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_github_workflows_do_not_reference_pre_restructure_paths() -> None:
    """CI must not call directories that commit 1 moved or archived."""
    forbidden = {
        r"(?<!packages/)apps/site": "bare apps/site",
        r"packages/terminal": "packages/terminal",
        r"packages/ai/tests": "packages/ai/tests",
        r"packages/automation/tests": "packages/automation/tests",
        r"packages/backtest-engine/tests": "packages/backtest-engine/tests",
        r"packages/core/tests": "packages/core/tests",
        r"packages/data/tests": "packages/data/tests",
        r"packages/ditto/tests": "packages/ditto/tests",
        r"packages/engine/tests": "packages/engine/tests",
        r"packages/gateway/tests": "packages/gateway/tests",
        r"packages/historical/tests": "packages/historical/tests",
        r"packages/indicators/tests": "packages/indicators/tests",
        r"packages/integration/tests": "packages/integration/tests",
        r"packages/screener/tests": "packages/screener/tests",
        r"packages/tick-engine/tests": "packages/tick-engine/tests",
    }
    offenders: list[str] = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        text = workflow.read_text(encoding="utf-8")
        for pattern, label in sorted(forbidden.items()):
            if re.search(pattern, text):
                offenders.append(f"{workflow.relative_to(ROOT)} contains {label}")

    assert offenders == []


def test_root_documents_use_restructure_lowercase_names() -> None:
    """Commit 1 renames root documentation files to lowercase names."""
    tracked = set(
        subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    )
    expected = {
        "readme.md",
        "changelog.md",
        "contributing.md",
        "code-of-conduct.md",
        "security.md",
        "notice",
    }
    forbidden = {
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "NOTICE",
    }

    missing = sorted(expected - tracked)
    still_present = sorted(forbidden & tracked)

    assert missing == []
    assert still_present == []


def test_root_license_is_regular_file_and_matches_tracked_license_bundle() -> None:
    """The GitHub licence entry must be clone-safe on every supported OS."""
    license_path = ROOT / "LICENSE"
    assert license_path.exists()
    assert not license_path.is_symlink()
    assert license_path.read_text(encoding="utf-8") == (
        ROOT / "licenses" / "agpl-3.0.txt"
    ).read_text(encoding="utf-8")

    expected = {
        "agpl-3.0.txt",
        "apache-2.0.txt",
        "cc-by-4.0.txt",
        "plug-in-exception.txt",
    }
    missing = sorted(name for name in expected if not (ROOT / "licenses" / name).is_file())
    assert missing == []


def test_runtime_code_does_not_use_pre_restructure_repo_paths() -> None:
    """Backend/site code must resolve files from the new package layout."""
    production_roots = [
        ROOT / "packages" / "core" / "core" / "src",
        ROOT / "packages" / "apps" / "site" / "scripts",
        ROOT / "packages" / "apps" / "terminal" / "src",
    ]
    forbidden = {
        "packages/terminal",
        "packages/backtest-engine",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
    }
    offenders: list[str] = []
    for production_root in production_roots:
        for path in sorted(production_root.rglob("*")):
            if path.suffix not in {".py", ".ts", ".tsx", ".mjs"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in sorted(forbidden):
                if token in text:
                    offenders.append(f"{path.relative_to(ROOT)} contains {token}")

    assert offenders == []


def test_site_vercel_config_uses_workspace_pnpm_lockfile() -> None:
    """Vercel deploys should use the workspace package manager and frozen lockfile."""
    vercel_config = json.loads((ROOT / "packages" / "apps" / "site" / "vercel.json").read_text(encoding="utf-8"))

    install_command = vercel_config.get("installCommand", "")
    build_command = vercel_config.get("buildCommand", "")

    assert "pnpm install --frozen-lockfile" in install_command
    assert build_command == "pnpm run build"
    assert re.search(r"(^|[;&|]\s*)npm(?:\s|$)", install_command) is None
    assert re.search(r"(^|[;&|]\s*)npm(?:\s|$)", build_command) is None


def test_make_dev_starts_flinttrade_backend_not_openalgo() -> None:
    """Local dev should boot FlintTrade's own backend; OpenAlgo is an optional integration."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    start_body = re.search(r"^start:.*?(?=^\S|\Z)", makefile, flags=re.MULTILINE | re.DOTALL)
    dev_body = re.search(r"^dev:.*?(?=^\S|\Z)", makefile, flags=re.MULTILINE | re.DOTALL)

    assert start_body is not None
    assert dev_body is not None
    assert "flinttrade_core.app" in start_body.group(0)
    assert "flinttrade_core.app" in dev_body.group(0)
    assert "FLINTTRADE_PYTHONPATH" in start_body.group(0)
    assert "FLINTTRADE_PYTHONPATH" in dev_body.group(0)
    assert "packages/core/core/src" in makefile
    assert "openalgo/start-openalgo.sh" not in start_body.group(0)
    assert "openalgo/start-openalgo.sh" not in dev_body.group(0)


def test_runtime_entrypoints_treat_openalgo_as_optional() -> None:
    """Ops helpers should manage FlintTrade first; OpenAlgo is an optional integration."""
    deploy = (ROOT / "infra" / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    rollback = (ROOT / "infra" / "scripts" / "rollback.sh").read_text(encoding="utf-8")
    health = (ROOT / "infra" / "scripts" / "health-check.sh").read_text(encoding="utf-8")
    status = (ROOT / "infra" / "scripts" / "status.sh").read_text(encoding="utf-8")
    service = (ROOT / "infra" / "systemd" / "flinttrade.service").read_text(encoding="utf-8")
    cron_readme = (ROOT / "infra" / "cron" / "README.md").read_text(encoding="utf-8")
    docs_readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "systemctl restart flinttrade" in deploy
    assert "systemctl restart flinttrade" in rollback
    assert "systemctl restart openalgo" not in deploy
    assert "systemctl restart openalgo" not in rollback
    assert "Requires=openalgo" not in service
    assert "FlintTrade backend responding" in health
    assert "OpenAlgo integration not responding" in health
    assert "OpenAlgo integration (optional)" in status
    assert "built\non top of" not in docs_readme
    assert re.search(r"optional\s+OpenAlgo-compatible bridge", docs_readme)
    assert "Ping FlintTrade backend health" in cron_readme


def test_terminal_key_primitives_delegate_to_design_system() -> None:
    """The terminal keeps legacy import paths while key primitives come from the shared core package."""
    expected = {
        "packages/apps/terminal/src/components/ui/button.tsx": "@flinttrade/design-system",
        "packages/apps/terminal/src/components/ui/card.tsx": "@flinttrade/design-system",
        "packages/apps/terminal/src/components/brand/Logo.tsx": "@flinttrade/design-system",
        "packages/apps/terminal/src/lib/utils.ts": "@flinttrade/design-system",
    }

    for path, token in expected.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        assert token in text


def test_terminal_custom_overlays_use_design_system_layer_contract() -> None:
    """Custom app overlays should share the same stacking scale as Radix primitives."""
    layers = (ROOT / "packages" / "core" / "design-system" / "src" / "layers.ts").read_text(encoding="utf-8")
    assert "floatingPanel" in layers
    assert 'z-[120]' in layers

    expected = [
        "packages/apps/terminal/src/chrome/QuickAccessPanel.tsx",
        "packages/apps/terminal/src/components/CommandPalette/PaletteShell.tsx",
        "packages/apps/terminal/src/components/NotificationCentre/NotificationCentre.tsx",
        "packages/apps/terminal/src/components/NoConnectionOverlay.tsx",
    ]
    for path in expected:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "layerClassNames" in text


def test_reset_state_restart_uses_flinttrade_backend_module() -> None:
    """The fresh-install helper should restart the same backend module as make start."""
    script = (ROOT / "scripts" / "reset-flinttrade-state.sh").read_text(encoding="utf-8")

    assert "-m flinttrade_core.app" in script
    assert "python -m packages.core.src.app" not in script


def test_native_setup_does_not_create_env_for_normal_source_setup() -> None:
    """Normal setup must not turn .env into a required native/source step."""
    script = (ROOT / "infra" / "scripts" / "setup.sh").read_text(encoding="utf-8")

    assert "cp \"$FLINTTRADE_DIR/.env.example\" \"$FLINTTRADE_DIR/.env\"" not in script
    assert "No .env required for native/source setup" in script


def test_server_installer_keeps_openalgo_config_in_ui() -> None:
    """The advanced server installer may have an EnvironmentFile, but not OpenAlgo-first setup."""
    installer = (ROOT / "infra" / "install" / "install-native.sh").read_text(encoding="utf-8")
    docker_installer = (ROOT / "infra" / "install" / "install-docker.sh").read_text(encoding="utf-8")

    assert "cp \"$INSTALL_DIR/.env.example\" \"$INSTALL_DIR/.env\"" not in installer
    assert "Set OPENALGO_API_KEY" not in installer
    assert "Settings -> Broker Gateway" in installer
    assert "cp \"$INSTALL_DIR/.env.example\" \"$INSTALL_DIR/.env\"" not in docker_installer
    assert "Set OPENALGO_API_KEY" not in docker_installer
    assert "Settings -> Broker Gateway" in docker_installer


def test_server_installers_use_live_backend_entrypoint_and_optional_openalgo() -> None:
    """Server installers should not point systemd at retired package paths or require OpenAlgo."""
    installer = (ROOT / "infra" / "install" / "install-native.sh").read_text(encoding="utf-8")
    systemd_unit = (ROOT / "infra" / "systemd" / "flinttrade.service").read_text(encoding="utf-8")
    docker_installer = (ROOT / "infra" / "install" / "install-docker.sh").read_text(encoding="utf-8")

    assert "-m flinttrade_core.app" in installer
    assert "packages.core.src.app" not in installer
    assert "flinttrade_core.app:app" in systemd_unit
    assert "packages.core.src.app:app" not in systemd_unit
    assert "Environment=FLINTTRADE_HOME=$INSTALL_DIR" in installer
    assert "Environment=FLINTTRADE_HOME=/opt/flinttrade" in systemd_unit
    assert 'FLINTTRADE_HOME="/home/$FLINTTRADE_USER"' not in installer
    assert "INSTALL_OPENALGO_SERVICE" in installer
    assert "Requires=flinttrade-backend.service" in installer
    assert "Requires=flinttrade-openalgo.service" not in installer
    assert "ps --format '{{.Status}}' flinttrade " in docker_installer
    assert "ps --format '{{.Status}}' flinttrade-backend" not in docker_installer


def test_desktop_release_workflow_is_manual_and_fail_closed() -> None:
    """Desktop release CI should be manual and fail if installers are missing."""
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    vuln_refresh = (ROOT / ".github" / "workflows" / "refresh-vuln-snapshot.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "description: 'Release tag to publish under" in workflow
    assert "push:" not in workflow
    assert "tags:" not in workflow
    assert "Verify release tag matches package version" in workflow
    assert "DESKTOP_VERSION" in workflow
    assert "TAURI_VERSION" in workflow
    assert "Release version mismatch" in workflow
    assert "Release tag $RELEASE_TAG points at $TAG_COMMIT" in workflow
    assert "not this workflow run's commit $GITHUB_SHA" in workflow
    assert "BUNDLE_ARGS+=(--bundles nsis)" in workflow
    assert "WiX/MSI rejects beta SemVer" in workflow
    assert "uv sync --frozen --extra desktop" in workflow
    assert 'if-no-files-found: error' in workflow
    assert 'fail_on_unmatched_files: true' in workflow
    assert "No installers were produced" in workflow
    assert "--output \"supply-chain/vuln-snapshot-${DATE}.json\" || true" not in vuln_refresh
    assert "pip-audit did not write a usable snapshot" in vuln_refresh
    assert "exit 1" in vuln_refresh
    assert "pip-audit failed with status" in vuln_refresh


def test_release_versions_are_aligned() -> None:
    """Release tags, package metadata, and desktop installer metadata should agree."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    desktop_package = json.loads((ROOT / "packages" / "apps" / "desktop" / "package.json").read_text(encoding="utf-8"))
    tauri_config = json.loads(
        (ROOT / "packages" / "apps" / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"),
    )

    assert version.startswith("v")
    bare_version = version.removeprefix("v")
    assert root_package["version"] == bare_version
    assert desktop_package["version"] == bare_version
    assert tauri_config["version"] == bare_version
    for pyproject in sorted(ROOT.glob("packages/*/*/pyproject.toml")):
        assert f'version = "{bare_version}"' in pyproject.read_text(encoding="utf-8"), pyproject


def test_current_beta_release_note_exists() -> None:
    """The current VERSION should have matching per-version release notes."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    release_note = ROOT / "docs" / "releases" / f"{version}.md"
    site_generator = (ROOT / "packages" / "apps" / "site" / "scripts" / "generate-content.mjs").read_text(
        encoding="utf-8",
    )

    assert release_note.exists()
    text = release_note.read_text(encoding="utf-8")
    assert version in text
    assert "not production ready" in text
    assert f"docs/releases/{version}.md" in site_generator


def test_supply_chain_covers_desktop_rust_lockfile() -> None:
    """Rust audit CI should cover the desktop installer lockfile as well as ticks."""
    workflow = (ROOT / ".github" / "workflows" / "supply-chain.yml").read_text(encoding="utf-8")
    cargo_allowlist = (ROOT / "supply-chain" / "cargo-audit-allowlist.yml").read_text(encoding="utf-8")
    cargo_script = (ROOT / "scripts" / "cargo-audit-with-allowlist.py").read_text(encoding="utf-8")

    assert "scripts/cargo-audit-with-allowlist.py" in workflow
    assert "--manifest-dir packages/core/ticks" in workflow
    assert "--manifest-dir packages/apps/desktop/src-tauri" in workflow
    assert "packages/apps/desktop/src-tauri/cargo-audit-report.json" in workflow
    assert "RUSTSEC-2024-0429" in cargo_allowlist
    assert "glib" in cargo_allowlist
    assert "expires:" in cargo_allowlist
    assert "Vulnerabilities are never suppressed" in cargo_script


def test_workspace_example_documents_ui_owned_openalgo_config() -> None:
    """workspace.example.json should describe OpenAlgo as UI/workspace config."""
    workspace_example = (ROOT / "workspace.example.json").read_text(encoding="utf-8")

    assert "Setup/Settings" in workspace_example
    assert "authoritative connection settings are in .env" not in workspace_example
    assert "OpenAlgo host/ports) lives in .env" not in workspace_example
