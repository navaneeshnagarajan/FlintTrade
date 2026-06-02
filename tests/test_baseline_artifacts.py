"""Regression checks for public baseline artefacts."""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tomllib
from io import StringIO
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "flinttrade-design" / "baselines"


def _repo_visible_paths() -> set[str]:
    return set(
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    )


def test_baseline_manifest_paths_are_public_repo_artefacts() -> None:
    manifest = json.loads((BASELINES / "MANIFEST.json").read_text(encoding="utf-8"))
    visible_paths = _repo_visible_paths()

    missing: list[str] = []
    local_paths: list[str] = []
    ignored_or_external_files: list[str] = []
    for artefact in manifest["artefacts"]:
        for rel_path in artefact["paths"]:
            path = ROOT / rel_path
            if rel_path.startswith(".local/"):
                local_paths.append(rel_path)
            if not path.exists():
                missing.append(rel_path)
            if path.is_file() and rel_path not in visible_paths:
                ignored_or_external_files.append(rel_path)

    assert local_paths == []
    assert missing == []
    assert ignored_or_external_files == []


def test_baseline_csv_schemas_are_stable() -> None:
    expected_headers = {
        "packages-2026-05-23.csv": [
            "current_key",
            "current_path",
            "target_path",
            "new_pypi_name",
            "new_import_name",
        ],
        "blueprints-2026-05-23.csv": [
            "blueprint_name",
            "current_url_prefix",
            "line_number",
            "target_url_prefix",
            "methods",
            "owner_package",
            "duplicate_flag",
        ],
        "operator-data-2026-05-23.csv": [
            "file",
            "owner_package",
            "engine",
            "locked_during_restructure",
            "migration_rule",
        ],
    }

    for filename, expected in expected_headers.items():
        with (BASELINES / filename).open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        assert reader.fieldnames == expected
        assert rows, f"{filename} should not be empty"


def test_public_rollback_runbook_covers_safe_restore_topics() -> None:
    runbook = BASELINES / "rollback-runbook-2026-05-24.md"
    text = runbook.read_text(encoding="utf-8")
    lowered = text.lower()

    for required in [
        "git revert",
        "vercel rollback",
        "license symlink",
        "~/.flinttrade/",
        "broker credentials",
        "post-rollback verification",
    ]:
        assert required in lowered

    for required in [
        "rollback rehearsal",
        "scripts/rehearse-baseline-rollback.py",
        "git merge-tree",
        "conflict indicators",
        "do not declare the rollback clean",
    ]:
        assert required in lowered


def test_rollback_rehearsal_script_defines_safe_conflict_report_contract() -> None:
    script_path = ROOT / "scripts" / "rehearse-baseline-rollback.py"
    assert script_path.exists()

    spec = importlib.util.spec_from_file_location("rehearse_baseline_rollback", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sample = "\n".join(
        [
            "changed in both",
            "  base   100644 abc packages/apps/terminal/src/routes/HomeRoute.tsx",
            "removed in local",
            "removed in remote",
            "CONFLICT (content): Merge conflict in readme.md",
            "",
        ]
    )

    summary = module.summarise_merge_tree(sample)

    assert summary.line_count == 5
    assert summary.conflict_indicators == 4
    assert summary.changed_in_both == 1
    assert summary.removed_in_local == 1
    assert summary.removed_in_remote == 1
    assert summary.clean is False


def test_rollback_rehearsal_tolerates_binary_merge_tree_output() -> None:
    script_path = ROOT / "scripts" / "rehearse-baseline-rollback.py"
    spec = importlib.util.spec_from_file_location("rehearse_baseline_rollback", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    decoded = module.decode_git_output(b"changed in both\n\xa9 invalid utf8\n")
    summary = module.summarise_merge_tree(decoded)

    assert "\ufffd" in decoded
    assert summary.conflict_indicators == 1


def test_dump_blueprints_script_runs_against_current_app_path() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/dump-blueprints.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    reader = csv.DictReader(StringIO(result.stdout))
    rows = list(reader)

    assert reader.fieldnames == [
        "blueprint_name",
        "current_url_prefix",
        "line_number",
        "target_url_prefix",
        "methods",
        "owner_package",
        "duplicate_flag",
    ]
    assert any(row["blueprint_name"] == "auth_bp" for row in rows)
    assert any(row["blueprint_name"] == "data_sandbox_bp" for row in rows)


def test_blueprint_baseline_matches_dumper_output() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/dump-blueprints.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    expected = result.stdout.replace("\r\n", "\n")
    actual = (BASELINES / "blueprints-2026-05-23.csv").read_text(encoding="utf-8").replace("\r\n", "\n")

    assert actual == expected


def test_package_baseline_targets_cover_current_package_paths() -> None:
    flint = tomllib.loads((ROOT / "flint.toml").read_text(encoding="utf-8"))
    expected_paths = {entry["path"] for entry in flint["packages"].values()}

    with (BASELINES / "packages-2026-05-23.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    actual_paths: set[str] = set()
    for row in rows:
        for target in row["target_path"].split(" + "):
            target = target.strip().strip('"')
            if target.startswith("packages/"):
                actual_paths.add(target)

    assert actual_paths == expected_paths


def test_operator_data_inventory_tracks_current_storage_engines() -> None:
    with (BASELINES / "operator-data-2026-05-23.csv").open(encoding="utf-8", newline="") as handle:
        rows = {row["file"]: row for row in csv.DictReader(handle)}

    assert rows["activity.db"]["engine"] == "sqlite WAL"
    assert rows["security.db"]["engine"] == "sqlite WAL"
    assert rows["sandbox/state.sqlite"]["engine"] == "sqlite WAL"
    assert "migrate legacy sandbox.duckdb" in rows["sandbox/state.sqlite"]["migration_rule"]


def test_pre_restructure_baseline_tag_verifies_with_tracked_allowed_signers() -> None:
    tag_exists = subprocess.run(
        ["git", "tag", "--list", "pre-restructure-baseline"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not tag_exists:
        pytest.skip("pre-restructure-baseline tag is not available in this clone")

    result = subprocess.run(
        [
            "git",
            "-c",
            f"gpg.ssh.allowedSignersFile={BASELINES / 'pre-restructure-baseline.allowed-signers'}",
            "tag",
            "-v",
            "pre-restructure-baseline",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Good \"git\" signature for navaneeshnagarajan@gmail.com" in result.stderr
    assert "82c2b391c5dcd2677df9132891b25ee2d0dae981" in result.stdout


def test_visual_regression_baseline_inventory_matches_route_matrix() -> None:
    root = BASELINES / "visual-regression" / "d2ae362"
    terminal_routes = [
        "root",
        "welcome",
        "explore",
        "setup",
        "setup-account",
        "home",
        "trade",
        "terminal",
        "invest",
        "learn",
        "lab",
        "automate",
        "ai",
        "ditto",
        "settings",
        "admin",
        "login",
        "missing-route-for-404",
    ]
    site_routes = [
        "root",
        "docs",
        "api-reference",
        "mcp",
        "contribute",
        "api-mcp",
        "api-search",
        "missing-route-for-404",
    ]
    viewports = ["1920x1080", "1366x768", "768x1024"]
    themes = ["dark", "light"]
    densities = ["compact", "comfortable"]

    expected: set[Path] = set()
    for app, routes in {"terminal": terminal_routes, "site": site_routes}.items():
        for route in routes:
            for viewport in viewports:
                for theme in themes:
                    for density in densities:
                        expected.add(root / app / route / viewport / theme / f"{density}.png")

    actual = set(root.rglob("*.png"))

    assert len(actual) == 312
    assert actual == expected


def test_visual_regression_capture_script_seeds_current_terminal_state() -> None:
    script = (ROOT / "scripts" / "generate-visual-regression-baseline.sh").read_text(encoding="utf-8")

    for required in [
        "terminalInitState",
        "waitForTerminalRoute",
        "allowLandmarkMatch",
        '"flinttrade-theme"',
        '"flinttrade:settings"',
        '"flinttrade:mode"',
        '"flinttrade:demoChoice"',
        '"flinttrade:demo-session"',
        '"flinttrade:tourComplete"',
        '"flinttrade:dailyWelcomeDismissed"',
        '"flinttrade:smallScreenDismissed"',
        '"/welcome": "Explore FlintTrade"',
        '"/setup": "Welcome to FlintTrade"',
        '"/setup-account": "Set up FlintTrade"',
        '"/login": "Page not found"',
    ]:
        assert required in script

    assert 'localStorage.setItem("flinttrade.theme", theme)' in script
    assert "if (app === \"terminal\")" in script


def test_visual_regression_policy_keeps_forensic_baseline_immutable() -> None:
    policy = (BASELINES / "visual-regression-policy.md").read_text(encoding="utf-8").lower()

    for required in [
        "forensic baseline",
        "d2ae362",
        "pre-restructure-baseline",
        "do not overwrite",
        "current release baseline",
        "verify-visual-regression-capture.py",
        "312",
    ]:
        assert required in policy


def test_visual_regression_capture_validator_defines_current_matrix(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "verify_visual_regression_capture",
        ROOT / "scripts" / "verify-visual-regression-capture.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    expected = module.expected_paths(tmp_path)

    assert len(expected) == 312
    assert expected[tmp_path / "terminal" / "trade" / "1920x1080" / "dark" / "comfortable.png"] == (1920, 1080)
    assert expected[tmp_path / "site" / "root" / "768x1024" / "light" / "compact.png"] == (768, 1024)

    result = subprocess.run(
        [sys.executable, "scripts/verify-visual-regression-capture.py", str(tmp_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "expected=312 actual=0" in result.stdout
    assert "missing=312" in result.stdout


def test_doc_sync_commit_zero_requirements_track_current_public_baselines() -> None:
    spec = importlib.util.spec_from_file_location("check_doc_sync", ROOT / "scripts" / "check_doc_sync.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    required = module.REQUIRED_BY_COMMIT["0"]
    visible_paths = _repo_visible_paths()

    assert "packages/core/core/src/workspace_migrations.py" not in required
    assert "packages/core/core/src/flinttrade_core/workspace_migrations.py" in required
    assert "flinttrade-design/baselines/pre-restructure-baseline.allowed-signers" in required
    assert "flinttrade-design/baselines/rollback-runbook-2026-05-24.md" in required
    assert "flinttrade-design/baselines/visual-regression-policy.md" in required
    assert "scripts/generate-visual-regression-baseline.sh" in required
    assert "scripts/rehearse-baseline-rollback.py" in required
    assert "scripts/verify-visual-regression-capture.py" in required
    assert "tests/test_baseline_artifacts.py" in required

    missing = sorted(path for path in required if not (ROOT / path).exists())
    ignored_or_external = sorted(path for path in required if (ROOT / path).is_file() and path not in visible_paths)

    assert missing == []
    assert ignored_or_external == []
