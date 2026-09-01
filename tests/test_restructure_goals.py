"""Regression checks for the v0.6.0 restructure repository shape."""

from __future__ import annotations

import json
import re
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


#: Vercel rejects a configuration whose buildCommand or installCommand exceeds this,
#: before the build starts and without emitting a build log.
_VERCEL_COMMAND_MAX_CHARS = 256


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
    """Vercel deploys must run the *pinned* pnpm against a frozen lockfile.

    Vercel's build image ships its own pnpm - 10.28.0 when this was written - and
    does not honour the ``packageManager`` pin, because Corepack is not enabled
    there. pnpm will not fetch its own pin either: ``pnpm-workspace.yaml`` sets
    ``managePackageManagerVersions: false`` deliberately. So the deploy resolves
    the pin from the root ``package.json`` itself and hands it to
    ``npx --package``, which runs that exact release instead of whatever ``pnpm``
    happens to sit on ``PATH``.

    ``packageManagerStrictVersion: true`` stays on: it is what turns "wrong pnpm"
    into a failed deploy rather than a lockfile quietly resolved by a version it
    was never written for. Bypassing it would defeat ``--frozen-lockfile``.

    The pin is asserted to be *absent* as a literal - deriving it is the point, and
    a second copy would be one more place to forget on the next bump.

    Both commands delegate to scripts because Vercel caps ``buildCommand`` and
    ``installCommand`` at 256 characters and rejects the whole configuration
    without ever starting a build - which it did, silently, with no build log to
    read.
    """
    site = ROOT / "packages" / "apps" / "site"
    vercel_config = json.loads((site / "vercel.json").read_text(encoding="utf-8"))

    install_command = vercel_config.get("installCommand", "")
    build_command = vercel_config.get("buildCommand", "")

    for name, command in (("installCommand", install_command), ("buildCommand", build_command)):
        assert len(command) <= _VERCEL_COMMAND_MAX_CHARS, (
            f"vercel.json {name} is {len(command)} characters; Vercel's limit is "
            f"{_VERCEL_COMMAND_MAX_CHARS}. Over it, the deployment is rejected before the build "
            "starts and produces no build log at all. Move the logic into a script under "
            "packages/apps/site/scripts/ and call that."
        )

    scripts = {
        "installCommand": site / "scripts" / "vercel-install.sh",
        "buildCommand": site / "scripts" / "vercel-build.sh",
    }
    for name, script in scripts.items():
        assert script.is_file(), f"vercel.json {name} delegates to {script.name}, which is missing."
        command = install_command if name == "installCommand" else build_command
        assert script.name in command, f"vercel.json {name} must invoke {script.name}."

    runner = site / "scripts" / "vercel-pnpm.sh"
    assert runner.is_file(), "packages/apps/site/scripts/vercel-pnpm.sh is missing."
    runner_body = runner.read_text(encoding="utf-8")
    install_body = scripts["installCommand"].read_text(encoding="utf-8")
    build_body = scripts["buildCommand"].read_text(encoding="utf-8")

    assert "install --frozen-lockfile" in install_body
    assert "run build" in build_body
    for name, body in (("vercel-install.sh", install_body), ("vercel-build.sh", build_body)):
        assert "vercel-pnpm.sh" in body, (
            f"{name} must go through vercel-pnpm.sh, or Vercel's own stale pnpm runs the command. "
            "`pnpm run` trips the same strict-version gate as `pnpm install`."
        )
        assert re.search(r"exec\s+sh\s", body), (
            f"{name} must invoke vercel-pnpm.sh through an explicit `sh`, not execute it directly. "
            "Tracked shell scripts here carry a shebang but not the exec bit, so a direct exec "
            "fails with 'Permission denied' - which is how this failed on Vercel once already."
        )

    pinned_version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["packageManager"]
    pinned_version = pinned_version.removeprefix("pnpm@").split("+")[0]

    assert "packageManager" in runner_body, (
        "vercel-pnpm.sh must read the pnpm pin out of the root package.json packageManager field."
    )
    assert 'npx --yes --package "$pin" --' in runner_body, (
        "vercel-pnpm.sh must invoke the resolved pin via npx --package, which runs that exact "
        "release rather than the pnpm on PATH."
    )

    for name, body in (
        ("vercel.json installCommand", install_command),
        ("vercel.json buildCommand", build_command),
        ("vercel-pnpm.sh", runner_body),
        ("vercel-install.sh", install_body),
        ("vercel-build.sh", build_body),
    ):
        assert pinned_version not in body, (
            f"{name} hardcodes pnpm {pinned_version}. Derive it from the root package.json "
            "packageManager field instead - the pin has one home."
        )
        assert re.search(r"(^|[;&|]\s*)npm(?:\s|$)", body) is None, (
            f"{name} calls npm directly; the workspace is pnpm-managed."
        )
        for bypass in ("package-manager-strict", "COREPACK_ENABLE_STRICT"):
            assert bypass not in body, (
                f"{name} disables the pnpm version check via {bypass}. That lets a "
                "wrong pnpm resolve the lockfile differently - the exact failure --frozen-lockfile exists to stop."
            )


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
    assert "recommended OpenAlgo-compatible bridge" in docs_readme
    assert re.search(r"evidence-gated\s+native\s+broker contracts", docs_readme)
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
    assert "-m flinttrade_core.app" in systemd_unit
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
    """Electron release CI publishes exactly the supported installers and provenance."""
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    release_please = (ROOT / ".github" / "workflows" / "release-please.yml").read_text(encoding="utf-8")
    vuln_refresh = (ROOT / ".github" / "workflows" / "refresh-vuln-snapshot.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "description: 'Release tag to publish under" in workflow
    assert "expected_sha:" in workflow
    assert "Required when publishing" in workflow
    assert "push:" not in workflow
    assert "tags:" not in workflow
    assert "group: desktop-release-${{ inputs.tag || github.ref }}" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "Verify release tag matches package version" in workflow
    assert "DESKTOP_VERSION" in workflow
    assert "VERSION_TAG" in workflow
    assert "TAURI_VERSION" not in workflow
    assert "Release version mismatch" in workflow
    assert "Release tag $RELEASE_TAG points at $TAG_COMMIT" in workflow
    assert "not this workflow run's immutable commit $GITHUB_SHA" in workflow
    assert "historical tags are never rebuilt" in workflow
    assert "merge-base --is-ancestor" not in workflow
    assert "source_sha: ${{ steps.release.outputs.source_sha }}" in workflow
    assert 'echo "source_sha=$SOURCE_SHA" >> "$GITHUB_OUTPUT"' in workflow
    assert workflow.count("ref: ${{ needs.validate.outputs.source_sha }}") >= 2
    assert workflow.count("Verify immutable tag and empty target release") == 1
    assert workflow.count("ASSET_COUNT=") == 2
    assert workflow.count("git fetch --force --no-tags origin") >= 3
    for label in ("macos-universal", "windows-x64", "linux-x64", "linux-arm64"):
        assert f"label: {label}" in workflow
    for name in (
        "FlintTrade-${VERSION}-mac-universal.dmg",
        "FlintTrade-${VERSION}-win-x64.exe",
        "FlintTrade-${VERSION}-linux-x64.AppImage",
        "FlintTrade-${VERSION}-linux-arm64.AppImage",
    ):
        assert name in workflow
    assert "SHA256SUMS.txt" in workflow
    assert "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8 # v4.2.2" in workflow
    assert "permissions:\n  contents: read" in workflow
    publish_job = workflow.split("\n  publish:\n", 1)[1]
    assert "permissions:\n      contents: write\n      attestations: write\n      id-token: write" in publish_job
    assert "attestations: write" in workflow
    assert "id-token: write" in workflow
    assert "APPLE_CERTIFICATE" in workflow
    assert "APPLE_SIGNING_IDENTITY" in workflow
    assert 'MAC_IDENTITY="-"' in workflow
    assert "MAC_HARDENED_RUNTIME=false" in workflow
    assert "--config.mac.hardenedRuntime=\"$MAC_HARDENED_RUNTIME\"" in workflow
    assert "FLINTTRADE_REQUIRE_DISTRIBUTION_SIGNATURE=1" in workflow
    assert 'if [[ "$MAC_IDENTITY" != "-" && "$present" -ne 3 ]]' in workflow
    assert "Distribution-signed macOS releases require the complete Apple notarisation secret trio." in workflow
    assert 'if-no-files-found: error' in workflow
    assert 'fail_on_unmatched_files: true' in workflow
    assert "prerelease: ${{ contains(inputs.tag, '-') }}" in workflow
    assert "target_commitish: ${{ needs.validate.outputs.source_sha }}" in workflow
    assert 'overwrite_files: false' in workflow
    assert 'overwrite_files: true' not in workflow
    assert "Re-verify immutable tag and exact published asset set" in workflow
    assert "Published release asset set is not canonical" in workflow
    assert "--method DELETE" not in workflow
    assert "Retire non-canonical" not in workflow
    assert "No installers were produced" in workflow
    assert "sha: ${{ steps.release.outputs.sha }}" in release_please
    assert "EXPECTED_SHA: ${{ needs.release-please.outputs.sha }}" in release_please
    assert '--ref "$RELEASE_TAG"' in release_please
    assert '-f expected_sha="$EXPECTED_SHA"' in release_please
    forbidden_release_paths = (
        "src-tauri",
        "cargo",
        "rust-toolchain",
        "rust-cache",
        "setup-python",
        "python",
        "setup-uv",
        "pyinstaller",
        "payload",
        "minisign",
        "latest.json",
        "flinttrade-desktop-manifest",
        "updater-beta",
        "updater-stable",
        "uv sync",
    )
    lower_workflow = workflow.lower()
    for token in forbidden_release_paths:
        assert token not in lower_workflow
    assert "--output \"supply-chain/vuln-snapshot-${DATE}.json\" || true" not in vuln_refresh
    assert "pip-audit did not write a usable snapshot" in vuln_refresh
    assert "exit 1" in vuln_refresh
    assert "pip-audit failed with status" in vuln_refresh


def _workflow_paths(workflow_dir: Path) -> list[Path]:
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


def _uses_value_nodes(node: Node) -> Iterator[Node]:
    """Yield every structurally parsed ``uses`` value at any YAML depth."""
    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, ScalarNode) and key_node.value == "uses":
                yield value_node
            yield from _uses_value_nodes(value_node)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _uses_value_nodes(item)


def _yaml_comment_column(source_line: str, start_column: int) -> int | None:
    """Locate the first real YAML comment after a scalar, ignoring quoted ``#``."""
    in_single_quote = False
    in_double_quote = False
    column = start_column
    while column < len(source_line):
        character = source_line[column]
        if in_single_quote:
            if character == "'":
                if column + 1 < len(source_line) and source_line[column + 1] == "'":
                    column += 2
                    continue
                in_single_quote = False
        elif in_double_quote:
            if character == "\\":
                column += 2
                continue
            if character == '"':
                in_double_quote = False
        elif character == "'":
            in_single_quote = True
        elif character == '"':
            in_double_quote = True
        elif character == "#" and (column == 0 or source_line[column - 1].isspace()):
            return column
        column += 1

    return None


def _has_readable_source_label(
    source_lines: list[str],
    value_node: Node,
    uses_value_nodes: list[Node],
) -> bool:
    """Return whether a real YAML comment unambiguously labels this external pin."""
    line_number = value_node.end_mark.line
    if line_number >= len(source_lines):
        return False
    if sum(node.end_mark.line == line_number for node in uses_value_nodes) != 1:
        return False

    source_line = source_lines[line_number]
    comment_column = _yaml_comment_column(source_line, value_node.end_mark.column)
    if comment_column is None:
        return False

    between_value_and_comment = source_line[value_node.end_mark.column : comment_column]
    if re.fullmatch(r"[\s\]}]*", between_value_and_comment) is None:
        return False

    label = source_line[comment_column + 1 :]
    return re.search(r"[A-Za-z0-9]", label) is not None


def _workflow_action_pin_violations(workflow_paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in workflow_paths:
        source = path.read_text(encoding="utf-8")
        source_lines = source.splitlines()
        try:
            document = yaml.compose(source)
        except yaml.YAMLError as error:
            mark = getattr(error, "problem_mark", None)
            line_number = mark.line + 1 if mark is not None else 1
            problem = getattr(error, "problem", None) or str(error).splitlines()[0]
            violations.append(
                f"{path.name}:{line_number}: malformed workflow YAML: {problem}"
            )
            continue

        if not isinstance(document, MappingNode):
            violations.append(f"{path.name}:1: workflow YAML must be a mapping")
            continue

        uses_value_nodes = list(_uses_value_nodes(document))
        for value_node in uses_value_nodes:
            line_number = value_node.start_mark.line + 1
            if not isinstance(value_node, ScalarNode) or value_node.tag != "tag:yaml.org,2002:str":
                violations.append(
                    f"{path.name}:{line_number}: uses value must be a string"
                )
                continue

            target = value_node.value
            if target.startswith("./"):
                continue
            if target.startswith("docker://"):
                if (
                    re.fullmatch(r"docker://[^@\s]+@sha256:[0-9a-f]{64}", target) is None
                    or not _has_readable_source_label(
                        source_lines, value_node, uses_value_nodes
                    )
                ):
                    violations.append(f"{path.name}:{line_number}: {target}")
                continue

            action, separator, reference = target.rpartition("@")
            if (
                not separator
                or re.fullmatch(r"[^/\s]+/[^@\s]+", action) is None
                or re.fullmatch(r"[0-9a-f]{40}", reference) is None
                or not _has_readable_source_label(
                    source_lines, value_node, uses_value_nodes
                )
            ):
                violations.append(f"{path.name}:{line_number}: {target}")

    return violations


@pytest.mark.parametrize(
    ("name", "source", "expected_fragment"),
    (
        (
            "alternate-whitespace.yml",
            "jobs:\n  build:\n    steps:\n      - uses : actions/checkout@v7 # v7\n",
            "actions/checkout@v7",
        ),
        (
            "quoted-key.yml",
            'jobs:\n  build:\n    steps:\n      - "uses": actions/checkout@v7 # v7\n',
            "actions/checkout@v7",
        ),
        (
            "flow-mapping.yml",
            "jobs: {build: {steps: [{uses: actions/checkout@v7}]}} # v7\n",
            "actions/checkout@v7",
        ),
        (
            "nested-reusable.yml",
            "jobs:\n  delegated:\n    uses: owner/project/.github/workflows/check.yml@main # v1\n",
            "owner/project/.github/workflows/check.yml@main",
        ),
        (
            "malformed.yml",
            "jobs:\n  build: [\n",
            "malformed workflow YAML",
        ),
        (
            "non-string.yml",
            "jobs:\n  build:\n    steps:\n      - uses: [actions/checkout@v7]\n",
            "uses value must be a string",
        ),
        (
            "uppercase-sha.yml",
            f"jobs:\n  build:\n    steps:\n      - uses: actions/checkout@{'A' * 40} # v7\n",
            f"actions/checkout@{'A' * 40}",
        ),
        (
            "missing-label.yml",
            f"jobs:\n  build:\n    steps:\n      - uses: actions/checkout@{'a' * 40}\n",
            f"actions/checkout@{'a' * 40}",
        ),
        (
            "flow-hash-in-quoted-value.yml",
            "jobs: {build: {steps: [{uses: actions/checkout@"
            + "a" * 40
            + ', name: "# not a release comment"}]}}\n',
            f"actions/checkout@{'a' * 40}",
        ),
        (
            "flow-hash-after-escaped-double-quotes.yml",
            "jobs: {build: {steps: [{uses: actions/setup-node@"
            + "b" * 40
            + r', name: "quoted \"value # still text\""}]}}'
            + "\n",
            f"actions/setup-node@{'b' * 40}",
        ),
        (
            "flow-hash-after-doubled-single-quotes.yml",
            "jobs: {build: {steps: [{uses: actions/upload-artifact@"
            + "c" * 40
            + ", name: 'quoted ''value # still text'''}]}}\n",
            f"actions/upload-artifact@{'c' * 40}",
        ),
    ),
)
def test_workflow_action_pin_policy_detects_yaml_mutations(
    tmp_path: Path,
    name: str,
    source: str,
    expected_fragment: str,
) -> None:
    """Syntax changes must not hide mutable or malformed ``uses`` values."""
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")

    violations = _workflow_action_pin_violations([path])

    assert any(expected_fragment in violation for violation in violations), violations


def test_workflow_action_pin_policy_does_not_share_one_flow_label(
    tmp_path: Path,
) -> None:
    """One trailing comment cannot label two external ``uses`` scalars."""
    first = f"actions/checkout@{'a' * 40}"
    second = f"actions/setup-node@{'b' * 40}"
    path = tmp_path / "shared-flow-label.yml"
    path.write_text(
        f"jobs: {{build: {{steps: [{{uses: {first}}}, {{uses: {second}}}]}}}} # v7\n",
        encoding="utf-8",
    )

    violations = _workflow_action_pin_violations([path])

    assert len(violations) == 2, violations
    assert first in violations[0]
    assert second in violations[1]


def test_workflow_action_pin_policy_accepts_structural_local_and_pinned_forms(
    tmp_path: Path,
) -> None:
    """Local actions/workflows remain allowed and external references stay readable."""
    path = tmp_path / "accepted.yaml"
    path.write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        f"      - uses : actions/checkout@{'a' * 40} # v7\n"
        f'      - "uses": actions/download-artifact@{'d' * 40} # v8.0.1\n'
        '      - "uses": ./local-action\n'
        f"      - {{uses: actions/setup-node@{'b' * 40}}} # v7.0.0\n"
        f"      - uses: docker://ghcr.io/owner/image@sha256:{'e' * 64} # v1\n"
        "  local-reusable:\n"
        "    uses: ./.github/workflows/local.yml\n"
        "  external-reusable:\n"
        f"    uses: owner/project/.github/workflows/check.yml@{'c' * 40} # v1\n",
        encoding="utf-8",
    )

    assert _workflow_action_pin_violations([path]) == []


def test_workflow_action_pin_policy_discovers_yml_and_yaml_files(tmp_path: Path) -> None:
    """Adding either supported workflow suffix automatically expands the policy surface."""
    (tmp_path / "first.yml").write_text("jobs: {}\n", encoding="utf-8")
    (tmp_path / "second.yaml").write_text("jobs: {}\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("jobs: {}\n", encoding="utf-8")

    assert [path.name for path in _workflow_paths(tmp_path)] == ["first.yml", "second.yaml"]


def test_every_workflow_pins_external_actions_to_immutable_revisions() -> None:
    """Every external action in every workflow is immutable and labelled."""
    workflow_paths = _workflow_paths(WORKFLOWS)
    assert workflow_paths, "no workflow files found"
    unpinned = _workflow_action_pin_violations(workflow_paths)

    assert unpinned == []


def test_ci_runs_electron_desktop_build_and_cross_platform_package_smoke() -> None:
    """Frequent and nightly desktop gates exercise Electron, not the retired Rust shell."""
    test_workflow = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    nightly = (WORKFLOWS / "nightly-cross-platform.yml").read_text(encoding="utf-8")

    assert "electron-desktop-tests:" in test_workflow
    for command in ("typecheck", "test:electron", "bundle", "verify:package"):
        assert command in test_workflow
    assert "electron-builder --dir --linux --x64" in test_workflow
    assert "rust-desktop-tests:" not in test_workflow
    assert "packages/apps/desktop/src-tauri" not in test_workflow

    assert "desktop-electron-package-smoke:" in nightly
    for runner in ("macos-latest", "windows-latest", "ubuntu-latest"):
        assert runner in nightly
    for command in (
        "electron-builder --dir --mac",
        "electron-builder --dir --win --x64",
        "electron-builder --dir --linux --x64",
        "verify:package",
    ):
        assert command in nightly
    assert "electron-builder --dir --mac --universal" in nightly
    assert "desktop-rust-tests:" not in nightly
    assert "packages/apps/desktop/src-tauri" not in nightly


def test_native_promoter_harnesses_are_required_after_bundle() -> None:
    """Every packaging lane must exercise the native promoter it just bundled."""
    bundle = "pnpm --filter @flinttrade/desktop bundle"
    posix_harness = (
        "pnpm --filter @flinttrade/desktop exec node "
        "scripts/run-required-atomic-promoter-test.mjs"
    )
    windows_harness = "pnpm --filter @flinttrade/desktop test:windows-source-fs"

    workflows: dict[str, dict[str, object]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(document, dict), path
        workflows[path.name] = document

    # The two verification lanes pin ubuntu-24.04, matching flint.toml
    # [requirements].os_requires. They package `--dir` and verify the security
    # contract; they publish nothing, so the build host's glibc never reaches a
    # user. desktop-release.yml's Linux build legs stay on ubuntu-22.04/-arm on
    # purpose - they compile flinttrade-fs-promoter.node and ship it inside the
    # AppImage, which makes the build host's glibc the installer's real floor.
    required_posix = {
        ("test.yml", "electron-desktop-tests"): (None, "ubuntu-24.04"),
        ("supply-chain.yml", "electron-package-verification"): (None, "ubuntu-24.04"),
        ("nightly-cross-platform.yml", "desktop-electron-package-smoke"): (
            "runner.os != 'Windows'",
            None,
        ),
        ("desktop-release.yml", "build"): ("runner.os != 'Windows'", None),
    }
    required_windows = {
        ("nightly-cross-platform.yml", "desktop-electron-package-smoke"): "runner.os == 'Windows'",
        ("desktop-release.yml", "build"): "matrix.label == 'windows-x64'",
    }
    observed_posix: list[tuple[str, str, object]] = []
    observed_windows: list[tuple[str, str, object]] = []

    for workflow_name, workflow in workflows.items():
        jobs = workflow.get("jobs")
        assert isinstance(jobs, dict), workflow_name
        for job_name, raw_job in jobs.items():
            if not isinstance(raw_job, dict):
                continue
            steps = raw_job.get("steps", [])
            assert isinstance(steps, list), f"{workflow_name}:{job_name}"
            for raw_step in steps:
                if not isinstance(raw_step, dict):
                    continue
                run = raw_step.get("run")
                if run == posix_harness:
                    observed_posix.append((workflow_name, str(job_name), raw_step.get("if")))
                if isinstance(run, str) and windows_harness in run:
                    observed_windows.append((workflow_name, str(job_name), raw_step.get("if")))

    assert sorted(observed_posix) == sorted(
        (workflow_name, job_name, condition)
        for (workflow_name, job_name), (condition, _runner) in required_posix.items()
    )
    assert sorted(observed_windows) == sorted(
        (workflow_name, job_name, condition)
        for (workflow_name, job_name), condition in required_windows.items()
    )

    for (workflow_name, job_name), (condition, runner) in required_posix.items():
        jobs = workflows[workflow_name]["jobs"]
        assert isinstance(jobs, dict)
        job = jobs[job_name]
        assert isinstance(job, dict)
        if runner is not None:
            assert job.get("runs-on") == runner
        steps = job.get("steps")
        assert isinstance(steps, list)
        bundle_indexes = [index for index, step in enumerate(steps) if isinstance(step, dict) and step.get("run") == bundle]
        harness_steps = [
            (index, step)
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("run") == posix_harness
        ]
        assert len(bundle_indexes) == 1, f"{workflow_name}:{job_name}"
        assert len(harness_steps) == 1, f"{workflow_name}:{job_name}"
        harness_index, harness_step = harness_steps[0]
        assert bundle_indexes[0] < harness_index
        assert harness_step.get("if") == condition
        assert harness_step.get("continue-on-error") is not True

    for (workflow_name, job_name), condition in required_windows.items():
        jobs = workflows[workflow_name]["jobs"]
        assert isinstance(jobs, dict)
        job = jobs[job_name]
        assert isinstance(job, dict)
        steps = job.get("steps")
        assert isinstance(steps, list)
        bundle_indexes = [index for index, step in enumerate(steps) if isinstance(step, dict) and step.get("run") == bundle]
        harness_steps = [
            (index, step)
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("run") == windows_harness
        ]
        assert len(bundle_indexes) == 1, f"{workflow_name}:{job_name}"
        assert len(harness_steps) == 1, f"{workflow_name}:{job_name}"
        harness_index, harness_step = harness_steps[0]
        assert bundle_indexes[0] < harness_index
        assert harness_step.get("if") == condition
        assert harness_step.get("continue-on-error") is not True

    release_jobs = workflows["desktop-release.yml"]["jobs"]
    assert isinstance(release_jobs, dict)
    release_build = release_jobs["build"]
    assert isinstance(release_build, dict)
    release_steps = release_build["steps"]
    assert isinstance(release_steps, list)
    rebind_steps = [
        step
        for step in release_steps
        if isinstance(step, dict)
        and step.get("name") == "Rebuild and bind the macOS native promoter to the release identity"
    ]
    assert len(rebind_steps) == 1
    rebind = rebind_steps[0]
    assert rebind.get("if") == "runner.os == 'macOS'"
    assert rebind.get("continue-on-error") is not True
    rebind_run = rebind.get("run")
    assert isinstance(rebind_run, str)
    rebind_lines = [line.strip() for line in rebind_run.splitlines() if line.strip()]
    identity_assignment = 'FLINTTRADE_NATIVE_MAC_IDENTITY="$MAC_IDENTITY" \\'
    keychain_assignment = 'FLINTTRADE_NATIVE_MAC_KEYCHAIN="${CSC_KEYCHAIN:-}" \\'
    assert (
        rebind_lines.index(identity_assignment)
        < rebind_lines.index(keychain_assignment)
        < rebind_lines.index(bundle)
        < rebind_lines.index(posix_harness)
    )


def test_release_versions_are_aligned() -> None:
    """Release tags and Electron package metadata should agree."""
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    desktop_package = json.loads((ROOT / "packages" / "apps" / "desktop" / "package.json").read_text(encoding="utf-8"))

    assert version.startswith("v")
    bare_version = version.removeprefix("v")
    assert root_package["version"] == bare_version
    assert desktop_package["version"] == bare_version
    electron_version = desktop_package["devDependencies"]["electron"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", electron_version)
    assert desktop_package["build"]["electronVersion"] == electron_version
    nsis = desktop_package["build"]["nsis"]
    assert nsis["oneClick"] is True
    assert nsis["perMachine"] is False
    assert "allowToChangeInstallationDirectory" not in nsis
    assert nsis["uninstallDisplayName"] == "FlintTrade"
    for pyproject in sorted(ROOT.glob("packages/*/*/pyproject.toml")):
        assert f'version = "{bare_version}"' in pyproject.read_text(encoding="utf-8"), pyproject


def test_version_scripts_do_not_mutate_retired_desktop_metadata() -> None:
    """Version propagation treats package.json as the Electron desktop authority."""
    checker = (ROOT / "scripts" / "check-version-consistency.py").read_text(encoding="utf-8")
    apply_version = (ROOT / "scripts" / "apply-version.py").read_text(encoding="utf-8")

    assert '"packages/apps/desktop/package.json"' in checker
    assert "electronVersion" in checker
    assert "src-tauri" not in checker
    assert "src-tauri" not in apply_version
    assert "flinttrade-desktop" not in apply_version


def test_version_scripts_enforce_strict_release_semver_and_truthful_channel_copy() -> None:
    """Release propagation must agree with downstream release discovery."""
    checker = runpy.run_path(str(ROOT / "scripts" / "check-version-consistency.py"))
    apply_version = runpy.run_path(str(ROOT / "scripts" / "apply-version.py"))
    checker_pattern = checker["SEMVER_WITH_PRERELEASE"]
    tag_pattern = apply_version["TAG_RE"]

    for tag in ("v0.6.0", "v0.6.0-beta.14", "v10.20.30-beta.preview-1"):
        assert checker_pattern.fullmatch(tag), tag
        assert tag_pattern.fullmatch(tag), tag
    for tag in (
        "v01.2.3",
        "v1.02.3",
        "v1.2.03",
        "v1.2.3-01",
        "v1.2.3-beta..1",
        "v1.2.3-beta.",
    ):
        assert checker_pattern.fullmatch(tag) is None, tag
        assert tag_pattern.fullmatch(tag) is None, tag

    disclaimer = apply_version["_release_disclaimer"]
    assert "beta prerelease" in disclaimer("v0.7.0-beta.1")
    # Pre-1.0 (0.x) is never labelled stable: SemVer treats 0.x as unstable and
    # FlintTrade marks every 0.x release as a GitHub pre-release.
    assert "pre-release" in disclaimer("v0.7.0")
    assert "stable release" not in disclaimer("v0.7.0")
    assert "beta prerelease" not in disclaimer("v0.7.0")
    assert "not production ready" in disclaimer("v0.7.0")
    # A post-1.0 non-prerelease tag is the only thing labelled a stable release.
    assert "stable release" in disclaimer("v1.2.3")
    assert "not production ready" not in disclaimer("v1.2.3")


def test_version_consistency_guard_passes() -> None:
    """The broad version-consistency guard should cover every publishable surface."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check-version-consistency.py")],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout


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


def test_supply_chain_audits_ticks_and_verifies_electron_package() -> None:
    """Supply-chain CI retains tick Cargo audit and verifies the Electron directory."""
    workflow = (ROOT / ".github" / "workflows" / "supply-chain.yml").read_text(encoding="utf-8")
    cargo_allowlist = (ROOT / "supply-chain" / "cargo-audit-allowlist.yml").read_text(encoding="utf-8")
    cargo_script = (ROOT / "scripts" / "cargo-audit-with-allowlist.py").read_text(encoding="utf-8")

    assert "scripts/cargo-audit-with-allowlist.py" in workflow
    assert "--manifest-dir packages/core/ticks" in workflow
    assert "packages/core/ticks/cargo-audit-report.json" in workflow
    assert "packages/apps/desktop/src-tauri" not in workflow
    assert "electron-package-verification:" in workflow
    assert "electron-builder --dir --linux --x64" in workflow
    assert "verify:package" in workflow
    assert "allowlist: []" in cargo_allowlist
    assert "Tauri" not in cargo_allowlist
    assert "Vulnerabilities are never suppressed" in cargo_script
    assert "Tauri" not in cargo_script
    assert "RUSTSEC-2026-0194" not in cargo_allowlist


def test_dependency_provenance_gate_accepts_repo_local_cargo_patches() -> None:
    """Cargo target paths are not dependency sources; repo-local patches are allowed."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check-no-git-deps.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "dependency provenance OK" in result.stdout


def test_desktop_release_does_not_require_numba_stack() -> None:
    """Native desktop packaging must not force llvmlite builds on macOS Intel."""
    ditto_manifest = (ROOT / "packages" / "services" / "ditto" / "pyproject.toml").read_text(encoding="utf-8")
    default_deps = ditto_manifest.split("[project.optional-dependencies]", 1)[0]
    requirements = (ROOT / "requirements.lock").read_text(encoding="utf-8")

    assert '"numba>=' not in default_deps
    assert 'numba = ["numba>=' in ditto_manifest
    assert "llvmlite==" not in requirements
    assert "numba==" not in requirements


def test_workspace_example_documents_ui_owned_openalgo_config() -> None:
    """workspace.example.json should describe OpenAlgo as UI/workspace config."""
    workspace_example = (ROOT / "workspace.example.json").read_text(encoding="utf-8")

    assert "Setup/Settings" in workspace_example
    assert "authoritative connection settings are in .env" not in workspace_example
    assert "OpenAlgo host/ports) lives in .env" not in workspace_example
