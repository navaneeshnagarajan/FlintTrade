"""Contracts for the affected and exhaustive cross-platform check runner."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import shutil
import string
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_local.py"
NATIVE_THREAD_VARIABLES = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)


def _load_checks():
    assert SCRIPT.exists(), "the cross-platform local check planner is not implemented"
    name = "_flinttrade_local_checks_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_full_plan_covers_every_language_without_duplicate_terminal_typecheck() -> None:
    """An exhaustive success must cover the complete gate, including scripts tests."""
    checks = _load_checks()
    plan = checks.build_plan(
        {key: True for key in ("code", "python", "terminal", "desktop", "rust", "site", "docs", "dependencies")},
        python="python",
        python_command=["python", "-m", "pytest", "packages/core/core/tests", "tests", "scripts/__tests__"],
        pnpm=["pnpm"],
        cargo="cargo",
        pytest_env=dict.fromkeys(NATIVE_THREAD_VARIABLES, "1"),
    )
    commands = [list(check.argv) for check in plan]
    assert ["python", "-m", "pytest", "packages/core/core/tests", "tests", "scripts/__tests__"] in commands
    assert ["cargo", "test", "--manifest-path", "packages/core/ticks/Cargo.toml"] in commands
    assert ["python", "-m", "ruff", "check", "packages/", "tests/", "scripts/__tests__/"] in commands
    assert ["pnpm", "--dir", "packages/apps/terminal", "run", "lint"] in commands
    assert ["pnpm", "--dir", "packages/apps/terminal", "run", "build"] in commands
    assert ["pnpm", "--dir", "packages/apps/terminal", "run", "typecheck"] not in commands
    terminal_tests = [command for command in commands if "vitest" in command]
    assert len(terminal_tests) == 1
    assert "--maxWorkers=1" in terminal_tests[0]
    assert "--no-file-parallelism" in terminal_tests[0]
    for script in ("test", "typecheck", "build"):
        assert ["pnpm", "--dir", "packages/apps/site", "run", script] in commands
    for script in ("typecheck", "test:electron"):
        assert ["pnpm", "--dir", "packages/apps/desktop", "run", script] in commands
    assert ["python", "scripts/check_local.py", "--secrets"] in commands
    assert ["pnpm", "exec", "node", "--test", "scripts/__tests__/http-cache-semantics.test.mjs"] in commands


@pytest.mark.unit
def test_docs_plan_keeps_repository_invariants_without_package_suites() -> None:
    """Documentation feedback must retain repository guards without the full Python tree."""
    checks = _load_checks()
    plan = checks.build_plan(
        {"docs": True, "site": True},
        python="python",
        python_command=["python", "-m", "pytest", "tests", "scripts/__tests__"],
        pnpm=["pnpm"],
        cargo="cargo",
        pytest_env=dict.fromkeys(NATIVE_THREAD_VARIABLES, "1"),
    )
    commands = [list(check.argv) for check in plan]
    assert ["python", "-m", "pytest", "tests", "scripts/__tests__"] in commands
    assert not any("packages/core/core/tests" in command or command[0] == "cargo" for command in commands)
    assert not any("packages/apps/terminal" in command or "packages/apps/desktop" in command for command in commands)
    assert ["pnpm", "--dir", "packages/apps/site", "run", "test"] in commands


@pytest.mark.unit
def test_dependency_plan_checks_the_current_locks_notice_and_provenance_offline() -> None:
    """NOTICE-only edits must verify the current artefacts, not just helper unit tests."""
    checks = _load_checks()
    plan = checks.build_plan(
        {"dependencies": True},
        python="python",
        python_command=["python", "-m", "pytest", "tests", "scripts/__tests__"],
        pnpm=["pnpm"],
        pytest_env=dict.fromkeys(NATIVE_THREAD_VARIABLES, "1"),
    )
    commands = [list(check.argv) for check in plan]
    assert ["python", "scripts/check-brokers-lock.py"] in commands
    assert ["python", "scripts/generate-notice.py", "--check"] in commands
    assert ["python", "scripts/check-no-git-deps.py"] in commands
    assert ["python", "scripts/check-uv-lock-export-drift.py"] in commands
    assert ["pnpm", "exec", "node", "--test", "scripts/__tests__/http-cache-semantics.test.mjs"] in commands
    assert not any("install" in command or "audit" in command for command in commands)
    assert not any("packages/apps/terminal" in command or "packages/apps/desktop" in command for command in commands)
    assert ["python", "scripts/check_local.py", "--secrets"] in commands


@pytest.mark.unit
def test_secret_scan_reports_locations_without_disclosing_the_value(tmp_path: Path, capsys) -> None:
    """A detected credential must fail the gate without printing its secret material."""
    checks = _load_checks()
    source = tmp_path / "config.py"
    secret = "sk-" + "1234567890abcdefghijklmnop"
    source.write_text(f"token = {secret!r}\n", encoding="utf-8")
    assert checks.scan_secrets(tmp_path, paths=["config.py"]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "config.py:1" in output
    assert secret not in output


@pytest.mark.unit
@pytest.mark.parametrize("prefix", ["sk-", "sk-proj-", "sk-ant-api03-", "broker"])
@pytest.mark.parametrize("suffix", [".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".toml"])
def test_secret_scan_cli_covers_common_credentials_in_git_inventory(
    prefix: str, suffix: str, tmp_path: Path,
) -> None:
    """Tracked and unignored credentials fail with locations only; ignored files stay excluded."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    scanner = scripts / SCRIPT.name
    shutil.copyfile(SCRIPT, scanner)
    # Generate synthetic values at runtime, so the test source is not itself a credential fixture.
    body = "".join(random.Random(17).choices(string.ascii_letters + string.digits, k=48))
    secret = (prefix if prefix != "broker" else "") + body
    assignment = "BROKER_" + "API_KEY" if prefix == "broker" else "token"
    payload = f"# synthetic credential\n{assignment} = {secret!r}\n"
    tracked, untracked, ignored = (f"{name}{suffix}" for name in ("tracked", "untracked", "ignored"))
    for relative in (tracked, untracked, ignored):
        (tmp_path / relative).write_text(payload, encoding="utf-8")
    (tmp_path / ".gitignore").write_text(ignored + "\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env |= {"HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    for args in (["init", "-q"], ["add", "--", tracked]):
        subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    result = subprocess.run(
        [sys.executable, str(scanner), "--secrets"], cwd=tmp_path, env=env,
        capture_output=True, text=True, check=False, timeout=10,
    )
    # Do not use secret values in assertions: even a regression must not echo them.
    if secret in result.stdout + result.stderr:
        pytest.fail("The scanner disclosed synthetic credential material")
    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"Potential secret: {tracked}:2", f"Potential secret: {untracked}:2"]
    assert result.stderr == ""


@pytest.mark.unit
def test_secret_scan_fails_when_the_file_inventory_cannot_be_read(tmp_path: Path) -> None:
    """A missing Git inventory cannot masquerade as a clean credential scan."""
    checks = _load_checks()
    assert checks.scan_secrets(tmp_path) != 0


def _runner(monkeypatch, surfaces, *, changes=(), command_exit=0, pnpm=("pnpm",)):
    """Replace only costly/external command execution and the incoming Git diff."""
    checks = _load_checks()
    spec = importlib.util.spec_from_file_location("_local_check_ft_context", ROOT / "scripts" / "ft.py")
    assert spec is not None and spec.loader is not None
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    external_calls = []
    diff_calls = []
    load = runner._load_module_from_path

    def diff(**kwargs):
        diff_calls.append(kwargs)
        return changes

    classifier = SimpleNamespace(changed_paths=diff, classify_paths=lambda paths, full=False: surfaces)
    monkeypatch.setattr(runner, "_load_module_from_path",
                        lambda name, path: classifier if Path(path).name == "check_changes.py" else load(name, path))
    monkeypatch.setattr(runner, "resolve_python", lambda: "python")
    monkeypatch.setattr(runner, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "pnpm_argv", lambda: list(pnpm) if pnpm else None)
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    monkeypatch.setattr(runner, "run", lambda argv, **kwargs: external_calls.append(list(argv)) or command_exit)
    return checks, runner, external_calls, diff_calls


@pytest.mark.unit
def test_dry_run_prints_the_plan_and_checks_worktree_without_running_commands(monkeypatch, capsys) -> None:
    """Planning must include unsaved-to-Git changes and cannot claim a passing gate."""
    checks, runner, calls, diff_calls = _runner(monkeypatch, {"docs": True, "site": True}, changes=["README.md"])
    assert checks.run_checks(["--base", "main", "--dry-run", "--workers", "0"], runner=runner) == 0
    assert not calls
    assert diff_calls == [{"base": "main", "include_worktree": True, "root": ROOT}]
    output = capsys.readouterr().out
    assert "Gate: affected" in output
    assert "scripts/__tests__" in output
    assert "packages/core/core/tests" not in output
    assert "Dry run only; no check results." in output
    assert "passed" not in output


@pytest.mark.unit
def test_full_gate_fails_instead_of_skipping_missing_node_toolchain(monkeypatch, capsys) -> None:
    """An exhaustive gate cannot silently green when required Node checks cannot run."""
    checks, runner, calls, _ = _runner(monkeypatch, {"python": True, "terminal": True}, pnpm=())
    assert checks.run_checks(["--full", "--workers", "0"], runner=runner) == 1
    assert not calls
    output = capsys.readouterr()
    assert "Node/pnpm is required" in output.err
    assert "passed" not in output.out


@pytest.mark.unit
def test_dependency_only_gate_requires_the_node_toolchain(monkeypatch, capsys) -> None:
    """Dependency contracts need Node even when no frontend application is selected."""
    checks, runner, calls, _ = _runner(monkeypatch, {"dependencies": True}, pnpm=())
    assert checks.run_checks(["--workers", "0"], runner=runner) == 1
    assert not calls
    output = capsys.readouterr()
    assert "Node/pnpm is required" in output.err
    assert "passed" not in output.out


@pytest.mark.unit
def test_offline_node_dependency_contract_failure_stops_the_actual_plan(monkeypatch, capsys) -> None:
    """A failing patched-dependency contract cannot be hidden by successful Python guards."""
    checks, runner, _, _ = _runner(monkeypatch, {"dependencies": True})
    calls = []
    contract = ["pnpm", "exec", "node", "--test", "scripts/__tests__/http-cache-semantics.test.mjs"]

    def execute(argv, **kwargs):
        calls.append(list(argv))
        return 17 if list(argv) == contract else 0

    monkeypatch.setattr(runner, "run", execute)
    assert checks.run_checks(["--workers", "0"], runner=runner) == 17
    assert calls[-1] == contract
    assert ["python", "scripts/check_local.py", "--secrets"] not in calls
    output = capsys.readouterr()
    assert "failed (exit 17). Gate did not pass." in output.err
    assert "Affected checks passed" not in output.out


@pytest.mark.unit
def test_failed_check_retains_exit_code_and_stops_later_suites(monkeypatch, capsys) -> None:
    """A failed prerequisite must stop the gate rather than running or hiding later checks."""
    checks, runner, calls, _ = _runner(monkeypatch, {"python": True}, command_exit=9)
    assert checks.run_checks(["--full", "--workers", "0"], runner=runner) == 9
    assert len(calls) == 1
    assert calls[0] == ["python", "scripts/check-version-consistency.py"]
    output = capsys.readouterr()
    assert "Gate did not pass" in output.err
    assert "gate passed" not in output.out


@pytest.mark.unit
def test_affected_success_does_not_claim_full_verification(monkeypatch, capsys) -> None:
    """A frontend/docs feedback pass must leave the exhaustive push gate explicit."""
    checks, runner, calls, _ = _runner(monkeypatch, {"docs": True, "site": True})
    assert checks.run_checks(["--workers", "0"], runner=runner) == 0
    assert any("pytest" in command for command in calls)
    assert all("packages/core/core/tests" not in command for command in calls)
    output = capsys.readouterr().out
    assert "Affected checks passed; full pre-push gate remains required." in output
    assert "Full local gate passed" not in output


@pytest.mark.unit
def test_missing_diff_selects_and_labels_the_exhaustive_fallback(monkeypatch, capsys) -> None:
    """An unresolved base must choose the safe full plan and make that fallback visible."""
    checks, runner, calls, _ = _runner(monkeypatch, {"python": True, "terminal": True}, changes=None)
    assert checks.run_checks(["--dry-run", "--workers", "0"], runner=runner) == 0
    assert not calls
    output = capsys.readouterr().out
    assert "Gate: full" in output
    assert "Changed paths unavailable" in output
    assert "packages/core/core/tests" in output


@pytest.mark.unit
@pytest.mark.parametrize("package_tests", [True, False])
def test_fixed_pytest_child_bounds_native_threads_and_clears_selection(
    package_tests: bool, tmp_path: Path, monkeypatch
) -> None:
    """Full and invariant test children get bounds without leaking them to other checks."""
    for variable in NATIVE_THREAD_VARIABLES:
        monkeypatch.setenv(variable, "64")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-m unit")
    checks, runner, _, _ = _runner(monkeypatch, {"python": package_tests, "docs": True})
    environments = []

    def execute(argv, *, env, **kwargs):
        if "pytest" not in argv:
            environments.append(env)
            return 0
        result = subprocess.run(
            [sys.executable, "-c", "import json, os, sys; print(json.dumps({name: os.environ.get(name) "
             "for name in sys.argv[1:]}))", *NATIVE_THREAD_VARIABLES, "PYTEST_ADDOPTS"],
            env=env, check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        child = json.loads(result.stdout)
        assert {name: child[name] for name in NATIVE_THREAD_VARIABLES} == dict.fromkeys(NATIVE_THREAD_VARIABLES, "1")
        assert child["PYTEST_ADDOPTS"] == ""
        return result.returncode

    monkeypatch.setattr(runner, "run", execute)
    assert checks.run_checks(["--full", "--workers", "0"], runner=runner) == 0
    assert environments
    assert all(all(env[name] == "64" for name in NATIVE_THREAD_VARIABLES) for env in environments)


@pytest.mark.unit
@pytest.mark.parametrize("selection", ["marker", "shard"])
def test_fixed_gate_cannot_hide_a_failure_through_inherited_pytest_options(
    selection: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    """User marker/shard preferences must never shrink a gate that claims exhaustive verification."""
    tests = tmp_path / "test_sample.py"
    tests.write_text(
        "import pytest\n"
        "@pytest.mark.unit\n"
        "@pytest.mark.parametrize('value', range(20))\n"
        "def test_fast(value): assert value >= 0\n"
        "def test_failure(): assert False, 'full gate must expose this failure'\n",
        encoding="utf-8",
    )
    configuration = tmp_path / "pytest.ini"
    configuration.write_text("[pytest]\nmarkers =\n    unit: quick feedback\n", encoding="utf-8")
    failing_shard = int.from_bytes(hashlib.sha256(b"test_sample.py::test_failure").digest(), "big") % 2
    addopts = "-m unit" if selection == "marker" else (
        f"-p scripts.pytest_shard --ft-shard-index={1 - failing_shard} --ft-shard-count=2"
    )
    monkeypatch.setenv("PYTEST_ADDOPTS", addopts)
    checks, runner, _, _ = _runner(monkeypatch, {"python": True})

    def execute(argv, *, env, **kwargs):
        if "pytest" not in argv:
            return 0
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-c", str(configuration), f"--confcutdir={tmp_path}", str(tests), "-q"],
            cwd=ROOT, env=env | {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True, text=True, check=False, timeout=30,
        )
        return result.returncode

    monkeypatch.setattr(runner, "run", execute)
    assert checks.run_checks(["--full", "--workers", "0"], runner=runner) == 1
    output = capsys.readouterr()
    assert "Gate did not pass" in output.err
    assert "Full local gate passed" not in output.out


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX executable shim; pytest environment contract is platform independent")
@pytest.mark.parametrize("addopts", ["-p pytest_timeout", "-p no:pytest_timeout", "-p no:xdist -n 2"])
def test_public_check_cli_plans_plugins_against_the_gate_environment(addopts: str, tmp_path: Path) -> None:
    """The real gate must clear interactive flags before both planning and execution."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("ft.py", "broker_sdk_environment.py", "check_local.py", "check_changes.py"):
        shutil.copyfile(ROOT / "scripts" / name, scripts / name)
    for name in (
        "check-version-consistency.py", "check-site-url-consistency.py", "check-brokers-lock.py",
        "generate-notice.py", "check-no-git-deps.py", "check-uv-lock-export-drift.py",
    ):
        (scripts / name).write_text("# External prerequisite fixture.\n", encoding="utf-8")
    for directory in ("packages", "tests", "scripts/__tests__", "bin"):
        (tmp_path / directory).mkdir(exist_ok=True)
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (tmp_path / "tests/test_gate.py").write_text(
        "import os\n\n\n"
        "def test_gate(request):\n"
        "    assert os.environ['PYTEST_ADDOPTS'] == ''\n"
        "    assert request.config.getoption('timeout') > 0\n"
        "    assert request.config.getoption('timeout_method') == 'thread'\n"
        "    assert request.config.getoption('numprocesses', default=None) is None\n",
        encoding="utf-8",
    )
    corepack = tmp_path / "bin/corepack"
    corepack.write_text(f"#!{sys.executable}\n# External Node checks fixture.\n", encoding="utf-8")
    corepack.chmod(0o755)
    git = shutil.which("git")
    assert git is not None
    (tmp_path / "bin/git").symlink_to(git)
    env = {name: value for name, value in os.environ.items() if not name.startswith(("PYTEST_XDIST_", "GIT_"))}
    env |= {
        "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PATH": str(tmp_path / "bin"),
        "PYTEST_ADDOPTS": addopts, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": "",
        "FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "workspace"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    }
    subprocess.run([git, "init", "-q"], cwd=tmp_path, env=env, check=True, capture_output=True)
    result = subprocess.run(
        [sys.executable, str(scripts / "ft.py"), "check", "--full", "--workers", "0"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "Full local gate passed." in result.stdout


@pytest.mark.unit
def test_secret_scan_includes_typescript_sources(tmp_path: Path) -> None:
    """Credential scanning must not miss the terminal's primary source language."""
    checks = _load_checks()
    (tmp_path / "config.ts").write_text('const token = "sk-' + "a" * 24 + '";\n', encoding="utf-8")
    assert checks.scan_secrets(tmp_path, paths=["config.ts"]) == 1


@pytest.mark.unit
def test_secret_scan_unreadable_source_is_a_failure(tmp_path: Path, monkeypatch) -> None:
    """Unreadable tracked source must not count as a clean scan."""
    checks = _load_checks()
    (tmp_path / "config.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unreadable")))
    assert checks.scan_secrets(tmp_path, paths=["config.py"]) == 1
