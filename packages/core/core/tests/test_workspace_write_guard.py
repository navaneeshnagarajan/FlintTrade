"""Architecture guard: workspace writes have one lock/CAS owner.

The behavioural CAS/restore suites test the owner and delegate semantics. This
source guard prevents new production call sites from bypassing that boundary.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
OWNER = ROOT / "packages/core/core/src/flinttrade_core/workspace_migrations.py"


def _workspace_write_violations(source: str) -> list[int]:
    tree = ast.parse(source)
    violations = []
    scopes = [tree, *(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef))]
    for scope in scopes:
        names = set()

        def workspace(node, names=names):
            return any(
                isinstance(item, ast.Constant)
                and item.value == "workspace.json"
                or isinstance(item, ast.Name)
                and item.id in names
                or isinstance(item, ast.Attribute)
                and item.attr == "config_path"
                for item in ast.walk(node)
            )

        for _ in range(4):
            for node in ast.walk(scope):
                if isinstance(node, ast.Assign) and workspace(node.value):
                    names.update(target.id for target in node.targets if isinstance(target, ast.Name))
                if isinstance(node, ast.AnnAssign) and node.value and workspace(node.value):
                    if isinstance(node.target, ast.Name):
                        names.add(node.target.id)
        for node in ast.walk(scope):
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("workspace_migrations"):
                if any(alias.name in {"_atomic_write", "_migration_lock"} for alias in node.names):
                    violations.append(node.lineno)
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in {"write_text", "write_bytes", "_atomic_write", "write_secret_text", "write_secret_bytes"}:
                if workspace(node):
                    violations.append(node.lineno)
            if name in {"replace", "rename", "copy", "copy2", "copyfile", "move"}:
                if node.args and workspace(node.args[-1]):
                    violations.append(node.lineno)
            if name == "open" and workspace(node):
                mode_arguments = node.args if isinstance(node.func, ast.Attribute) else node.args[1:]
                modes = [argument.value for argument in mode_arguments if isinstance(argument, ast.Constant)]
                modes += [
                    keyword.value.value
                    for keyword in node.keywords
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant)
                ]
                if any(isinstance(mode, str) and any(flag in mode for flag in "wax+") for mode in modes):
                    violations.append(node.lineno)
    return sorted(set(violations))


@pytest.mark.parametrize(
    "source",
    [
        'p = root / "workspace.json"\np.open("w")',
        'p = root / "workspace.json"\np.write_text(payload)',
        'p = root / "workspace.json"\nq = p\nq.write_bytes(payload)',
        'open(root / "workspace.json", "w")',
        'p = root / "workspace.json"\nos.replace(candidate, p)',
        "workspace.config_path.write_text(payload)",
        "from flinttrade_core.workspace_migrations import _migration_lock as lock",
    ],
)
def test_writer_guard_detects_bypass_mutations(source):
    assert _workspace_write_violations(source)


def test_all_production_workspace_writes_use_public_cas_owner():
    failures = []
    paths = list((ROOT / "packages").glob("**/src/**/*.py")) + list((ROOT / "scripts").glob("**/*.py"))
    for path in paths:
        if path == OWNER:
            continue
        lines = _workspace_write_violations(path.read_text(encoding="utf-8"))
        if lines:
            failures.append(f"{path.relative_to(ROOT)}:{lines}")
    assert not failures, "Out-of-band workspace write/private owner access: " + "; ".join(failures)


def test_services_routing_has_no_production_readers_outside_persistence():
    failures = []
    for path in (ROOT / "packages").glob("**/src/**/*.py"):
        if path == OWNER:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            strings = {
                item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
            if "services.routing" in strings or {"services", "routing"} <= strings:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not failures, "Dormant service routing acquired a runtime reader: " + "; ".join(failures)


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _expression_is(node: ast.AST, expression: str) -> bool:
    return ast.unparse(node) == expression


def _keyword_matches(call: ast.Call, name: str, expression: str) -> bool:
    values = [keyword.value for keyword in call.keywords if keyword.arg == name]
    return len(values) == 1 and _expression_is(values[0], expression)


def _broker_dependency_chain_violations(source: str) -> list[str]:
    """Return deviations from the shared read/write dependency composition."""
    tree = ast.parse(source)
    composers = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "configure_broker_router"
    ]
    if len(composers) != 1:
        return ["configure_broker_router count"]

    calls = [node for node in ast.walk(composers[0]) if isinstance(node, ast.Call)]
    violations: list[str] = []
    prepare_calls = [call for call in calls if _call_name(call) == "_prepare_broker_dependencies"]
    if len(prepare_calls) != 1:
        violations.append("prepare call count")
    else:
        prepare = prepare_calls[0]
        if not _keyword_matches(prepare, "workspace_snapshot", "workspace_snapshot"):
            violations.append("prepare workspace_snapshot")
        if not _keyword_matches(prepare, "workspace_path", "target_workspace"):
            violations.append("prepare workspace_path")

    if any(_call_name(call) == "build_broker_router" for call in calls):
        violations.append("direct build_broker_router")

    owner_calls = [call for call in calls if _call_name(call) == "create_broker_read_owner"]
    owner_assignments = [
        node
        for node in ast.walk(composers[0])
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and _expression_is(node.targets[0], "dependencies.read_owner")
        and isinstance(node.value, ast.Call)
        and _call_name(node.value) == "create_broker_read_owner"
    ]
    if len(owner_calls) != 1:
        violations.append("read owner call count")
    if len(owner_assignments) != 1:
        violations.append("read owner assignment count")
    if len(owner_calls) == 1 and len(owner_assignments) == 1:
        owner = owner_calls[0]
        for name, expression in (
            ("registry", "dependencies.registry"),
            ("session_provider", "dependencies.session_provider"),
            ("adapters", "dependencies.adapters"),
            ("rate_limiter", "dependencies.rate_limiter"),
            ("workspace_path", "target_workspace"),
        ):
            if not _keyword_matches(owner, name, expression):
                violations.append(f"read owner {name}")

    write_calls = [call for call in calls if _call_name(call) == "_configure_broker_writes"]
    if len(write_calls) != 1:
        violations.append("write dependency call count")
    elif (
        len(write_calls[0].args) != 2
        or write_calls[0].keywords
        or not _expression_is(write_calls[0].args[0], "app")
        or not _expression_is(write_calls[0].args[1], "dependencies")
    ):
        violations.append("write dependency binding")
    return violations


def test_app_workspace_router_construction_cannot_omit_snapshot_binding():
    path = ROOT / "packages/core/core/src/flinttrade_core/app.py"
    violations = _broker_dependency_chain_violations(path.read_text(encoding="utf-8"))
    assert not violations, "Broken broker dependency composition: " + ", ".join(violations)


_VALID_BROKER_DEPENDENCY_CHAIN = """
def configure_broker_router(app):
    dependencies = _prepare_broker_dependencies(
        registry,
        workspace_snapshot=workspace_snapshot,
        workspace_path=target_workspace,
    )
    dependencies.read_owner = create_broker_read_owner(
        registry=dependencies.registry,
        session_provider=dependencies.session_provider,
        adapters=dependencies.adapters,
        rate_limiter=dependencies.rate_limiter,
        workspace_path=target_workspace,
    )
    return _configure_broker_writes(app, dependencies)
"""


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("        workspace_snapshot=workspace_snapshot,\n", "", "prepare workspace_snapshot"),
        ("        workspace_path=target_workspace,\n", "", "prepare workspace_path"),
        (
            "    dependencies = _prepare_broker_dependencies(\n",
            "    build_broker_router()\n    dependencies = _prepare_broker_dependencies(\n",
            "direct build_broker_router",
        ),
        (
            "    dependencies.read_owner = create_broker_read_owner(\n",
            "    discarded_owner = create_broker_read_owner(\n",
            "read owner assignment count",
        ),
        (
            "    return _configure_broker_writes(app, dependencies)\n",
            "    dependencies.read_owner = create_broker_read_owner()\n"
            "    return _configure_broker_writes(app, dependencies)\n",
            "read owner call count",
        ),
        ("        registry=dependencies.registry,\n", "        registry=registry,\n", "read owner registry"),
        (
            "        session_provider=dependencies.session_provider,\n",
            "        session_provider=session_provider,\n",
            "read owner session_provider",
        ),
        ("        adapters=dependencies.adapters,\n", "        adapters=adapters,\n", "read owner adapters"),
        (
            "        rate_limiter=dependencies.rate_limiter,\n",
            "        rate_limiter=rate_limiter,\n",
            "read owner rate_limiter",
        ),
        (
            "        rate_limiter=dependencies.rate_limiter,\n"
            "        workspace_path=target_workspace,\n",
            "        rate_limiter=dependencies.rate_limiter,\n",
            "read owner workspace_path",
        ),
        (
            "        rate_limiter=dependencies.rate_limiter,\n"
            "        workspace_path=target_workspace,\n",
            "        rate_limiter=dependencies.rate_limiter,\n"
            "        workspace_path=other_workspace,\n",
            "read owner workspace_path",
        ),
        (
            "    return _configure_broker_writes(app, dependencies)\n",
            "    return _configure_broker_writes(app, foreign_dependencies)\n",
            "write dependency binding",
        ),
        (
            "    return _configure_broker_writes(app, dependencies)\n",
            "    _configure_broker_writes(app, dependencies)\n"
            "    return _configure_broker_writes(app, dependencies)\n",
            "write dependency call count",
        ),
    ],
    ids=[
        "prepare-omits-snapshot",
        "prepare-omits-path",
        "compatibility-wrapper",
        "discarded-read-owner",
        "duplicate-read-owner",
        "foreign-registry",
        "foreign-session-provider",
        "foreign-adapters",
        "foreign-rate-limiter",
        "read-owner-omits-path",
        "read-owner-foreign-path",
        "foreign-write-dependencies",
        "duplicate-write-dependencies",
    ],
)
def test_broker_dependency_chain_guard_rejects_structural_regressions(old, new, expected):
    assert old in _VALID_BROKER_DEPENDENCY_CHAIN
    mutated = _VALID_BROKER_DEPENDENCY_CHAIN.replace(old, new, 1)
    assert expected in _broker_dependency_chain_violations(mutated)


def _nonpython_authority_write(source):
    direct = re.search(r"\brestic\b[^\n;]*\b(?:backup|restore)\b", source)
    copied_workspace = re.search(
        r"(?:cp\s+-r|Copy-Item|copytree).*\b(?:WORKSPACE\w*|FLINTTRADE_DIR|STATE_DIR)", source, re.IGNORECASE
    )
    literal_write = re.search(r"(?:writeFile|WriteAllText|write_text|fs::write|File::create).*workspace\.json", source)
    return bool(direct or copied_workspace or literal_write)


@pytest.mark.parametrize("source", [
    'restic -r "$RESTIC_REPOSITORY" backup "$WORKSPACE_DIR"',
    'restic -r "$RESTIC_REPOSITORY" restore "$SNAPSHOT" --target "$TARGET_DIR"',
    'cp -r "$STATE_DIR"/. "$ARCHIVE_DIR/"',
])
def test_nonpython_guard_detects_existing_command_shapes(source):
    assert _nonpython_authority_write(source)


def test_nonpython_inventory_detects_core_rust_workspace_writer(tmp_path, monkeypatch):
    import sys

    path = tmp_path / "packages/core/ticks/src/lib.rs"
    path.parent.mkdir(parents=True)
    path.write_text('std::fs::write(workspace.join("workspace.json"), payload);')
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    with pytest.raises(AssertionError, match="packages/core/ticks/src/lib.rs"):
        test_nonpython_authority_copy_inventory_has_no_new_unguarded_owner()


def test_nonpython_authority_copy_inventory_has_no_new_unguarded_owner():
    guarded = {"infra/backup/backup.sh", "infra/backup/restore.sh", "scripts/reset-flinttrade-state.sh"}
    failures = []
    for root in (ROOT / "infra", ROOT / "scripts", ROOT / "packages"):
        for path in root.rglob("*"):
            if path.suffix not in {".sh", ".ps1", ".ts", ".js", ".rs"} or any(
                part in {"node_modules", "dist", "target", "tests", "e2e"} for part in path.parts
            ):
                continue
            if ".test." in path.name:
                continue
            if not path.is_file():
                continue
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(ROOT).as_posix()
            if _nonpython_authority_write(source) and relative not in guarded:
                failures.append(relative)
    assert not failures, "New out-of-band authority writer requires admission: " + ", ".join(failures)


def test_make_and_installer_backup_delegates_reach_guarded_scripts_only():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("backup", "restore"):
        body = re.search(rf"^{target}:.*\n((?:\t.*\n)+)", makefile, re.MULTILINE)
        assert body is not None
        assert body.group(1).strip() == f"@bash infra/backup/{target}.sh"
    for installer in ("install-native.sh", "install-docker.sh"):
        source = (ROOT / "infra/install" / installer).read_text(encoding="utf-8")
        schedules = [line for line in source.splitlines() if "0 2 * * *" in line]
        assert schedules
        assert all("infra/backup/backup.sh" in line for line in schedules)
        assert not _nonpython_authority_write(source)
    docker = (ROOT / "infra/install/install-docker.sh").read_text(encoding="utf-8")
    wrapper = re.search(r'tee "\$MANAGEMENT_DIR/flinttrade-backup"[^\n]*\n(.*?)\nSCRIPT_EOF', docker, re.DOTALL)
    assert wrapper is not None
    assert wrapper.group(1).splitlines() == ["#!/usr/bin/env bash", "/opt/flinttrade/infra/backup/backup.sh"]


@pytest.mark.skipif(os.name != "posix" or shutil.which("bash") is None, reason="POSIX guarded command contracts")
@pytest.mark.parametrize(
    "script,args",
    [
        ("infra/backup/backup.sh", []),
        ("infra/backup/restore.sh", ["--target", "unused", "--snapshot", "fixture"]),
        ("scripts/reset-flinttrade-state.sh", ["--restart"]),
    ],
)
def test_inventory_authority_commands_are_unreachable_before_external_effects(tmp_path, script, args):
    result = subprocess.run(
        [shutil.which("bash"), str(ROOT / script), *args],
        cwd=tmp_path,
        env={"PATH": str(tmp_path), "HOME": str(tmp_path)},
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert result.stderr.strip() == "coordinated_restore_unavailable"
    assert not list(tmp_path.iterdir())
