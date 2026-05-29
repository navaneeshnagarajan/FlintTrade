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


def test_root_license_points_at_tracked_license_bundle() -> None:
    """Commit 1 keeps the GitHub licence entry while moving texts to licenses/."""
    license_path = ROOT / "LICENSE"
    assert license_path.exists()
    assert license_path.is_symlink()
    assert license_path.readlink() == Path("licenses/agpl-3.0.txt")

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
