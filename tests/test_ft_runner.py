"""Contract tests for ``scripts/ft.py``, the cross-platform task runner.

``ft.py`` is the entry point every Windows user runs and the one the install
shim wraps, yet it sits outside ``packages/`` so neither the package test suites
nor the ``git ls-files -- packages`` path guard can see it. These tests close
that hole and pin the four properties that have actually broken:

  1. The command table, the ``help`` output and the Makefile header describe the
     SAME set of subcommands, and every one of them dispatches. A command listed
     in the header but absent from ``COMMANDS`` exits 2 when a user runs it.
  2. :func:`ft.workspace_dir` agrees with ``flinttrade_core.workspace`` on every
     platform and both env overrides. ``ft.py`` cannot import the core resolver
     (it must run before any dependency is installed, since it is what installs
     them), so the duplication is deliberate — and therefore has to be policed.
  3. Interpreter resolution prefers the host's own virtualenv layout and rejects
     the Microsoft Store ``python.exe`` alias stub, which exits 49 without
     running anything.
  4. ``ft.py`` imports nothing outside the standard library, and joins
     ``PYTHONPATH`` with :data:`os.pathsep` rather than a hardcoded ``:``.

Everything here is hermetic: workspace paths and CLI subprocess fixtures are
redirected into ``tmp_path``. Public dispatch uses harmless stand-in tools and
processes; no backend, network or real user workspace is touched.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from flinttrade_core import workspace as core_workspace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FT_PATH = _REPO_ROOT / "scripts" / "ft.py"
_BOOTSTRAP_HELPER_PATH = _FT_PATH.with_name("broker_sdk_environment.py")
_LOCAL_CHECKS_PATH = _FT_PATH.with_name("check_local.py")
_CHANGE_CLASSIFIER_PATH = _FT_PATH.with_name("check_changes.py")
_MAKEFILE_PATH = _REPO_ROOT / "Makefile"


def _load_ft() -> ModuleType:
    """Import ``scripts/ft.py`` by path.

    It is a standalone script rather than a package module, so the normal import
    machinery cannot reach it.

    Returns:
        The imported ``ft`` module.
    """
    spec = importlib.util.spec_from_file_location("flinttrade_ft_runner_under_test", _FT_PATH)
    assert spec is not None and spec.loader is not None, f"could not load {_FT_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ft = _load_ft()
_NATIVE_THREAD_VARIABLES = (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS",
)


@pytest.mark.unit
def test_arbitrary_name_load_uses_the_exact_sibling_setup_helper(tmp_path: Path) -> None:
    """Path-based runner imports cannot be redirected by cwd or PYTHONPATH."""
    shadow_helper = tmp_path / "broker_sdk_environment.py"
    shadow_helper.write_text(
        "def remove_kotak_distributions(*args, **kwargs): pass\n"
        "def repair_kotakneo_environment(*args, **kwargs): pass\n",
        encoding="utf-8",
    )
    expected_helper = _FT_PATH.with_name("broker_sdk_environment.py").resolve()
    loader = (
        "import importlib.util, pathlib, sys\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location('arbitrary_ft_name', path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "actual = pathlib.Path(module.repair_kotakneo_environment.__code__.co_filename).resolve()\n"
        "assert actual == pathlib.Path(sys.argv[2]), (actual, sys.argv[2])\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", loader, str(_FT_PATH), str(expected_helper)],
        cwd=tmp_path,
        env=os.environ | {"PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_direct_runner_version_works_from_a_foreign_cwd(tmp_path: Path) -> None:
    """The documented script entry point runs from outside the repository."""
    result = subprocess.run(
        [sys.executable, str(_FT_PATH), "version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``Path.home()`` and clear the workspace env overrides.

    Both ``ft.py`` and ``flinttrade_core.workspace`` call ``Path.home()`` and
    read the same two env vars, so one fixture isolates both. ``HOME`` and
    ``USERPROFILE`` are redirected as well because ``Path.expanduser()`` goes
    through :func:`os.path.expanduser`, not ``Path.home``. The core resolver
    creates the directory it returns — under ``tmp_path`` that is harmless, and
    it is what keeps the real workspace untouched.

    Args:
        tmp_path: Per-test temporary directory.
        monkeypatch: Pytest patcher.

    Returns:
        The fake home directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    return home


# ---------------------------------------------------------------------------
# Command table / help / Makefile header
# ---------------------------------------------------------------------------


def _makefile_runner_commands() -> list[str]:
    """Parse the Makefile header's "Via scripts/ft.py" command list.

    Returns:
        Every subcommand the header claims the runner provides.
    """
    text = _MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^#\s+Via scripts/ft\.py:\s*$(.*?)^#\s+Plain Python/uv recipes",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "the Makefile header no longer lists the scripts/ft.py commands"
    body = " ".join(line.lstrip("# ").strip() for line in match.group(1).splitlines())
    return [name for name in (part.strip() for part in body.split(",")) if name]


@pytest.mark.unit
def test_every_documented_command_has_a_handler() -> None:
    """``COMMANDS`` and ``HANDLERS`` must describe the same set of subcommands."""
    assert set(ft.COMMANDS) == set(ft.HANDLERS), (
        "COMMANDS and HANDLERS disagree; documented-but-unhandled commands exit 2 for the user"
    )


@pytest.mark.unit
def test_help_output_lists_exactly_the_command_table(capsys: pytest.CaptureFixture[str]) -> None:
    """``ft.py help`` must render every command, and only the commands, in order."""
    assert ft.cmd_help([]) == 0
    out = capsys.readouterr().out

    marker = "Commands (Windows, macOS and Linux):"
    assert marker in out
    section = out.split(marker, 1)[1].split("make targets", 1)[0]
    listed = [line.split()[0] for line in section.splitlines() if line.startswith("  ") and line.strip()]

    assert listed == list(ft.COMMANDS)
    for name, description in ft.COMMANDS.items():
        assert description in out, f"help output does not describe {name}"


@pytest.mark.unit
def test_makefile_header_matches_the_command_table() -> None:
    """The Makefile header's runner list is the third surface and must not drift."""
    assert set(_makefile_runner_commands()) == set(ft.COMMANDS), (
        "the Makefile header and scripts/ft.py COMMANDS list different subcommands"
    )


@pytest.mark.unit
def test_start_gateway_is_an_alias_for_start() -> None:
    """``start-gateway`` is a Make alias for ``start``; the runner must mirror it."""
    assert ft.HANDLERS["start-gateway"] is ft.HANDLERS["start"]


@pytest.mark.unit
@pytest.mark.parametrize("command", sorted(ft.COMMANDS))
def test_every_documented_command_is_dispatchable(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``main`` must route every documented command to a handler, never to exit 2."""
    if command == "help":
        # `help` is short-circuited before the handler lookup.
        assert ft.main([command]) == 0
        capsys.readouterr()
        return

    seen: list[list[str]] = []

    def _record(args: list[str]) -> int:
        seen.append(args)
        return 0

    monkeypatch.setitem(ft.HANDLERS, command, _record)
    assert ft.main([command, "--flag"]) == 0
    assert seen == [["--flag"]]


@pytest.mark.unit
def test_unknown_command_reports_and_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    """An unrecognised subcommand exits 2 after printing the command table."""
    assert ft.main(["not-a-command"]) == 2
    captured = capsys.readouterr()
    assert "Unknown command: not-a-command" in captured.err
    assert "Commands (Windows, macOS and Linux):" in captured.out


# ---------------------------------------------------------------------------
# Workspace resolution parity with flinttrade_core.workspace
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
def test_workspace_dir_matches_core_on_every_platform(
    system: str,
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner's platform defaults must equal the core resolver's, byte for byte."""
    monkeypatch.setattr(platform, "system", lambda: system)
    if system == "Windows":
        monkeypatch.setenv("APPDATA", str(isolated_home / "AppData" / "Roaming"))
    else:
        monkeypatch.delenv("APPDATA", raising=False)

    assert ft.workspace_dir() == core_workspace.workspace_dir()


@pytest.mark.unit
def test_workspace_dir_matches_core_on_windows_without_appdata(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both resolvers fall back to ``~/AppData/Roaming`` when ``APPDATA`` is unset."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.delenv("APPDATA", raising=False)

    expected = isolated_home / "AppData" / "Roaming" / "flinttrade"
    assert ft.workspace_dir() == expected
    assert ft.workspace_dir() == core_workspace.workspace_dir()


@pytest.mark.unit
@pytest.mark.parametrize("env_name", ["FLINTTRADE_WORKSPACE_DIR", "FLINTTRADE_HOME"])
def test_workspace_dir_matches_core_for_each_env_override(
    env_name: str,
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both overrides are honoured, expanded AND resolved — exactly as the core does."""
    override = tmp_path / "override-workspace"
    override.mkdir()
    monkeypatch.setenv(env_name, str(override))

    resolved = ft.workspace_dir()
    assert resolved == override.resolve()
    assert resolved == core_workspace.workspace_dir()
    assert resolved.is_absolute()


@pytest.mark.unit
def test_workspace_dir_override_precedence_matches_core(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``FLINTTRADE_WORKSPACE_DIR`` beats ``FLINTTRADE_HOME`` in both resolvers."""
    preferred = tmp_path / "preferred"
    ignored = tmp_path / "ignored"
    preferred.mkdir()
    ignored.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(preferred))
    monkeypatch.setenv("FLINTTRADE_HOME", str(ignored))

    assert ft.workspace_dir() == preferred.resolve()
    assert ft.workspace_dir() == core_workspace.workspace_dir()


@pytest.mark.unit
def test_workspace_dir_expands_a_tilde_override(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``~``-prefixed override is expanded rather than taken literally."""
    monkeypatch.setenv("FLINTTRADE_HOME", "~/custom-workspace")
    assert ft.workspace_dir() == (isolated_home / "custom-workspace").resolve()


@pytest.mark.unit
def test_workspace_dir_never_creates_the_directory(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``status`` must be able to report a missing workspace, so the runner never mkdirs."""
    missing = tmp_path / "not-created-yet"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(missing))

    assert ft.workspace_dir() == missing.resolve()
    assert not missing.exists()


# ---------------------------------------------------------------------------
# Interpreter resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("is_windows", "expected_parts"),
    [(True, ("Scripts", "python.exe")), (False, ("bin", "python"))],
)
def test_resolve_python_prefers_the_host_venv_layout(
    is_windows: bool,
    expected_parts: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With both layouts present the host's own must win — the other cannot execute."""
    venv = tmp_path / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    (venv / "bin").mkdir(parents=True)
    (venv / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (venv / "bin" / "python").write_text("", encoding="utf-8")

    monkeypatch.setattr(ft, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ft, "IS_WINDOWS", is_windows)
    monkeypatch.setattr(ft, "probe_python", lambda _candidate: True)

    assert Path(ft.resolve_python()) == venv.joinpath(*expected_parts)


@pytest.mark.unit
def test_resolve_python_skips_a_venv_interpreter_that_does_not_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A present-but-broken virtualenv interpreter falls through to the running one."""
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(ft, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ft, "IS_WINDOWS", False)
    monkeypatch.setattr(ft, "probe_python", lambda _candidate: False)

    assert ft.resolve_python() == sys.executable


@pytest.mark.unit
def test_is_store_alias_only_matches_windowsapps_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stub is recognised by its ``WindowsApps`` directory, in either slash style."""
    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    assert ft.is_store_alias(r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python3.exe")
    assert ft.is_store_alias("C:/Users/x/AppData/Local/Microsoft/WindowsApps/python.exe")
    assert not ft.is_store_alias(r"C:\Python313\python.exe")

    monkeypatch.setattr(ft, "IS_WINDOWS", False)
    assert not ft.is_store_alias("/usr/bin/python3")


@pytest.mark.unit
def test_resolve_python_rejects_the_microsoft_store_alias_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stub exits 49 without running anything, so it must never be selected."""
    stub = tmp_path / "WindowsApps" / "python3.exe"
    stub.parent.mkdir(parents=True)
    stub.write_text("", encoding="utf-8")

    monkeypatch.setattr(ft, "REPO_ROOT", tmp_path / "no-venv-here")
    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    monkeypatch.setattr(ft.sys, "executable", str(stub))
    monkeypatch.setattr(ft.shutil, "which", lambda _name: str(stub))
    # The stub never runs the probe snippet, so probing it fails.
    monkeypatch.setattr(ft, "probe_python", lambda _candidate: False)

    with pytest.raises(SystemExit) as excinfo:
        ft.resolve_python()

    assert excinfo.value.code == 1
    assert "No usable Python interpreter found." in capsys.readouterr().err


@pytest.mark.unit
def test_resolve_python_accepts_a_genuine_store_installed_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Store-installed Python also lives under ``WindowsApps`` — probe, do not assume."""
    real = tmp_path / "WindowsApps" / "python3.exe"
    real.parent.mkdir(parents=True)
    real.write_text("", encoding="utf-8")

    monkeypatch.setattr(ft, "REPO_ROOT", tmp_path / "no-venv-here")
    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    monkeypatch.setattr(ft.sys, "executable", str(real))
    monkeypatch.setattr(ft.shutil, "which", lambda _name: str(real))
    monkeypatch.setattr(ft, "probe_python", lambda _candidate: True)

    assert ft.resolve_python() == str(real)


# ---------------------------------------------------------------------------
# Child environment
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cmd_test_pins_rust_build_to_the_resolved_python(monkeypatch: pytest.MonkeyPatch) -> None:
    """PyO3 must not discover an older ambient ``python`` than the pytest interpreter."""
    expected_python = "/repo/.venv/bin/python"
    calls: list[tuple[list[str], dict[str, str] | None, bool]] = []

    monkeypatch.setattr(ft, "_run_pytest", lambda _flags: 0)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/usr/bin/cargo" if name == "cargo" else None)
    monkeypatch.setattr(ft, "resolve_python", lambda: expected_python)

    def _record(
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        check: bool = True,
        quiet: bool = False,
    ) -> int:
        del cwd, quiet
        calls.append((list(argv), env, check))
        return 0

    monkeypatch.setattr(ft, "run", _record)

    assert ft.cmd_test([]) == 0
    assert calls[0][0] == ["/usr/bin/cargo", "test", "--manifest-path", "packages/core/ticks/Cargo.toml"]
    assert calls[0][1] is not None
    assert calls[0][1]["PYO3_PYTHON"] == expected_python
    assert calls[0][2] is False


@pytest.mark.unit
def test_test_command_keeps_an_explicit_pytest_target_focused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A supplied node id must not be expanded into every package suite."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/usr/bin/cargo" if name == "cargo" else None)

    target = "tests/test_ft_runner.py::test_unknown_command_reports_and_exits_two"
    assert ft.cmd_test([target, "-q"]) == 0
    assert len(calls) == 1, "focused Python feedback must not start Rust compilation"
    assert target in calls[0]
    assert "-q" in calls[0]
    assert "packages/core/core/tests" not in calls[0]
    assert "--timeout-method=thread" in calls[0]


@pytest.mark.unit
def test_pytest_keyword_selection_retains_all_default_test_roots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag values are not positional paths, and root pytest's testpaths is incomplete."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)

    assert ft.cmd_test(["-k", "workspace"]) == 0
    assert "packages/core/core/tests" in calls[0]
    assert "tests" in calls[0]
    assert "scripts/__tests__" in calls[0]
    assert calls[0][calls[0].index("-k") + 1] == "workspace"


@pytest.mark.unit
def test_test_fast_enforces_first_failure_after_forwarded_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Forwarding --maxfail must not disable test-fast's first-failure contract."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)

    assert ft.cmd_test_fast(["tests/test_ft_runner.py", "--maxfail=0"]) == 0
    assert "tests/test_ft_runner.py" in calls[0]
    assert calls[0].index("-x") > calls[0].index("--maxfail=0")
    assert "packages/core/core/tests" not in calls[0]


@pytest.mark.unit
def test_pytest_workers_are_bounded_when_xdist_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local runs must not allocate one worker for each CPU on large hosts."""
    calls: list[list[str]] = []
    monkeypatch.delenv("FLINTTRADE_TEST_WORKERS", raising=False)
    monkeypatch.setattr(ft.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: "")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)

    assert ft.cmd_test_fast(["tests/test_ft_runner.py"]) == 0
    assert calls[0][calls[0].index("-n") + 1] == "4"


@pytest.mark.unit
@pytest.mark.parametrize("override", [["--workers", "2"], ["--workers=2"]])
def test_pytest_worker_override_is_runner_only(
    override: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner consumes --workers instead of leaking an invalid option to pytest."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: "")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)

    assert ft.cmd_test_fast(["tests/test_ft_runner.py", *override]) == 0
    assert calls[0][calls[0].index("-n") + 1] == "2"
    assert not any(arg.startswith("--workers") for arg in calls[0])


def _copy_runner_fixture(root: Path) -> Path:
    """Run the real CLI in a disposable checkout, never the user's workspace."""
    scripts = root / "scripts"
    scripts.mkdir()
    for source in (_FT_PATH, _BOOTSTRAP_HELPER_PATH):
        shutil.copyfile(source, scripts / source.name)
    return scripts / "ft.py"


@pytest.mark.unit
@pytest.mark.parametrize("command", ["test", "test-fast"])
@pytest.mark.parametrize("override_source", ["cli", "environment"])
@pytest.mark.parametrize("addopts_source", ["environment", "configuration"])
def test_public_cli_serial_workers_override_inherited_parallelism(
    command: str, override_source: str, addopts_source: str, tmp_path: Path,
) -> None:
    """Zero workers must actively override pytest's inherited -n, not omit a flag."""
    runner = _copy_runner_fixture(tmp_path)
    configuration = tmp_path / "pytest.ini"
    configuration.write_text(
        "[pytest]\n" + ("addopts = -n 2\n" if addopts_source == "configuration" else ""), encoding="utf-8",
    )
    target = tmp_path / "test_serial.py"
    target.write_text(
        "import os\n"
        "def test_serial(request):\n"
        "    assert not os.environ.get('PYTEST_XDIST_WORKER'), 'serial override still started workers'\n"
        "    assert request.config.getoption('numprocesses') == 0\n",
        encoding="utf-8",
    )
    env = os.environ | {
        "PYTEST_ADDOPTS": "-n 2" if addopts_source == "environment" else "",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": "xdist.plugin",
        "FLINTTRADE_TEST_WORKERS": "0" if override_source == "environment" else "2",
        "FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "workspace"),
    }
    env = {name: value for name, value in env.items() if not name.startswith("PYTEST_XDIST_")}
    options = ["--workers", "0"] if override_source == "cli" else []
    result = subprocess.run(
        [sys.executable, str(runner), command, *options, str(target), "-c", str(configuration), "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "bringing up nodes" not in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["explicit-workers", "disabled-cli", "disabled-addopts", "autoload-disabled"])
def test_public_cli_serial_override_preserves_explicit_workers_and_plugin_disables(mode: str, tmp_path: Path) -> None:
    runner = _copy_runner_fixture(tmp_path)
    target = tmp_path / "test_plugin_options.py"
    assertion = (
        "os.environ.get('PYTEST_XDIST_WORKER_COUNT') == '1'" if mode == "explicit-workers"
        else "request.config.getoption('numprocesses', default=None) is None"
    )
    target.write_text(
        f"import os\ndef test_options(request):\n    assert {assertion}\n", encoding="utf-8",
    )
    configuration = tmp_path / "pytest.ini"
    configuration.write_text("[pytest]\n", encoding="utf-8")
    options = ["-n", "1"] if mode == "explicit-workers" else (["-p", "no:xdist"] if mode == "disabled-cli" else [])
    env = os.environ | {
        "PYTEST_ADDOPTS": "-p no:xdist" if mode == "disabled-addopts" else "",
        "PYTEST_PLUGINS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1" if mode == "autoload-disabled" else "",
        "FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "workspace"),
    }
    result = subprocess.run(
        [sys.executable, str(runner), "test-fast", "--workers", "0", str(target), "-c", str(configuration), *options],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("configuration_kind", ["ini", "toml", "setup-cfg", "override", "autoload"])
def test_public_cli_respects_configuration_plugin_disables(configuration_kind: str, tmp_path: Path) -> None:
    """Selected pytest configuration controls whether automatic worker flags are valid."""
    runner = _copy_runner_fixture(tmp_path)
    addopts = "--disable-plugin-autoload" if configuration_kind == "autoload" else "-p no:xdist"
    if configuration_kind == "toml":
        configuration = tmp_path / "custom.toml"
        content = f'[tool.pytest.ini_options]\naddopts = "{addopts}"\n'
    elif configuration_kind == "setup-cfg":
        configuration = tmp_path / "setup.cfg"
        content = f"[tool:pytest]\naddopts = {addopts}\n"
    else:
        configuration = tmp_path / "pytest.ini"
        content = "[pytest]\n" + ("" if configuration_kind == "override" else f"addopts = {addopts}\n")
    configuration.write_text(content, encoding="utf-8")
    target = tmp_path / "test_configuration.py"
    target.write_text(
        "def test_configuration(request):\n"
        "    assert request.config.getoption('numprocesses', default=None) is None\n"
        "    assert request.config.getoption('timeout') > 0\n"
        "    assert request.config.getoption('timeout_method') == 'thread'\n",
        encoding="utf-8",
    )
    options = ["-o", f"addopts={addopts}"] if configuration_kind == "override" else []
    env = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    env |= {"PYTEST_ADDOPTS": "", "PYTEST_PLUGINS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": ""}
    result = subprocess.run(
        [sys.executable, str(runner), "test-fast", str(target), "--workers", "0", "-c", str(configuration), *options],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("plugin", ["xdist", "pytest_timeout"])
@pytest.mark.parametrize("override_source", ["cli", "environment"])
def test_public_cli_applies_plugin_overrides_in_pytest_order(
    plugin: str, override_source: str, tmp_path: Path,
) -> None:
    """A later enable must undo a disable, including watchdog and worker defaults."""
    runner = _copy_runner_fixture(tmp_path)
    configuration = tmp_path / "pytest.ini"
    disable = f"-p no:{plugin}"
    enable = f"-p {plugin}"
    worker_opts = " -n 2" if plugin == "xdist" else ""
    configuration.write_text(
        "[pytest]\n" + (f"addopts = {disable}\n" if override_source == "environment" else ""),
        encoding="utf-8",
    )
    target = tmp_path / "test_plugin_order.py"
    target.write_text(
        "import os\n"
        "def test_plugin_order(request):\n"
        "    assert request.config.getoption('timeout') > 0\n"
        "    assert request.config.getoption('timeout_method') == 'thread'\n"
        + ("    assert os.environ.get('PYTEST_XDIST_WORKER_COUNT') == '1'\n" if plugin == "xdist" else ""),
        encoding="utf-8",
    )
    env = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    env |= {
        "PYTEST_ADDOPTS": (disable if override_source == "cli" else enable) + worker_opts,
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": "",
    }
    options = ["-p", plugin] if override_source == "cli" else []
    result = subprocess.run(
        [sys.executable, str(runner), "test-fast", str(target), "--workers", "1", "-c", str(configuration), *options],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


@pytest.mark.unit
def test_public_cli_plugin_probe_preserves_conftest_options_without_importing_it(tmp_path: Path) -> None:
    """Configuration probing must not execute project setup or consume custom flags."""
    runner = _copy_runner_fixture(tmp_path)
    configuration = tmp_path / "pytest.ini"
    configuration.write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "from pathlib import Path\n"
        "counter = Path(__file__).with_name('conftest-imports')\n"
        "counter.write_text(counter.read_text() + 'x' if counter.exists() else 'x')\n"
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--fixture-value')\n",
        encoding="utf-8",
    )
    target = tmp_path / "test_custom_option.py"
    target.write_text(
        "def test_custom_option(request):\n"
        "    assert request.config.getoption('fixture_value') == 'kept'\n",
        encoding="utf-8",
    )
    env = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_XDIST_")}
    env |= {"PYTEST_ADDOPTS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_PLUGINS": ""}
    result = subprocess.run(
        [sys.executable, str(runner), "test-fast", "--workers", "0", str(target), "-c", str(configuration),
         "--fixture-value", "kept"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert (tmp_path / "conftest-imports").read_text() == "x"


def _pid_running(pid: int) -> bool:
    """Treat an already dead orphan awaiting init's reap as stopped, on either POSIX host."""
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_until(predicate, *, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail("Timed out waiting for the harmless dev-process fixture")
        time.sleep(0.02)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group integration; Windows taskkill has a separate contract")
@pytest.mark.parametrize("ending", ["backend-failure", "interrupt", "terminate", "hangup", "nohup-hangup"])
@pytest.mark.parametrize("ignore_term", [False, True])
def test_public_dev_cli_cleans_owned_process_trees(
    ending: str, ignore_term: bool, tmp_path: Path,
) -> None:
    """Both dev trees stop even after a leader exits or a descendant ignores SIGTERM."""
    runner = _copy_runner_fixture(tmp_path)
    package = tmp_path / "packages/core/core/src/flinttrade_core"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "cli.py").write_text("# Harmless stand-in for first-run provisioning.\n", encoding="utf-8")
    (package / "app.py").write_text("from fake_dev import serve\nserve('backend')\n", encoding="utf-8")
    fake = tmp_path / "fake_dev.py"
    fake.write_text(
        "import os, pathlib, signal, subprocess, sys, time\n"
        "root = pathlib.Path(__file__).parent\n"
        "def serve(role):\n"
        "    if role.endswith('-child'):\n"
        "        if os.environ['IGNORE_TERM'] == '1':\n"
        "            signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    else:\n"
        "        subprocess.Popen([sys.executable, __file__, role + '-child'])\n"
        "    (root / (role + '.pid')).write_text(str(os.getpid()))\n"
        "    deadline = time.monotonic() + 60\n"
        "    while time.monotonic() < deadline:\n"
        "        if role == 'backend' and (root / 'observe-hup').exists():\n"
        "            (root / 'alive-after-hup').touch()\n"
        "        if role == 'backend' and (root / 'finish').exists():\n"
        "            raise SystemExit(7)\n"
        "        time.sleep(0.02)\n"
        "if __name__ == '__main__': serve(sys.argv[1])\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    corepack = bin_dir / "corepack"
    corepack.write_text(
        f"#!{sys.executable}\nfrom fake_dev import serve\nserve('terminal')\n", encoding="utf-8",
    )
    corepack.chmod(0o755)
    env = os.environ | {
        "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PATH": str(bin_dir), "PYTHONPATH": str(tmp_path),
        "FLINTTRADE_WORKSPACE_DIR": str(tmp_path / "workspace"), "FLINTTRADE_HOME": str(tmp_path / "workspace"),
        "IGNORE_TERM": str(int(ignore_term)),
    }
    pid_files = [tmp_path / f"{role}.pid" for role in ("backend", "backend-child", "terminal", "terminal-child")]
    command = [sys.executable, str(runner), "dev"]
    if ending == "nohup-hangup":
        nohup = shutil.which("nohup")
        if nohup is None:
            pytest.skip("nohup is unavailable on this POSIX host")
        command.insert(0, nohup)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    cli = subprocess.Popen(
        command, cwd=tmp_path, env=env, start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        _wait_until(lambda: all(path.exists() and path.stat().st_size for path in pid_files))
        pids = [int(path.read_text()) for path in pid_files]
        if ending in {"terminate", "hangup"}:
            termination_signal = signal.SIGTERM if ending == "terminate" else signal.SIGHUP
            os.killpg(cli.pid, termination_signal)
            expected_code = -termination_signal
        elif ending == "interrupt":
            cli.send_signal(signal.SIGINT)
            expected_code = 0
        else:
            if ending == "nohup-hangup":
                os.killpg(cli.pid, signal.SIGHUP)
                (tmp_path / "observe-hup").touch()
                _wait_until(lambda: (tmp_path / "alive-after-hup").exists())
                assert cli.poll() is None, "Inherited ignored SIGHUP must not stop the supervisor"
            (tmp_path / "finish").touch()
            expected_code = 7
        stdout, stderr = cli.communicate(timeout=15)
        assert cli.returncode == expected_code, stdout + stderr
        assert unrelated.poll() is None, "Cleanup must not touch a process it did not launch"
        _wait_until(lambda: not any(_pid_running(pid) for pid in pids), timeout=2)
    finally:
        # Tear down only fixture-created processes even when the regression is red.
        for path in pid_files:
            if path.exists() and path.stat().st_size:
                pid = int(path.read_text())
                if _pid_running(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        if cli.poll() is None:
            cli.kill()
        cli.communicate(timeout=5)
        unrelated.kill()
        unrelated.wait(timeout=5)


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX signal disposition contract")
@pytest.mark.parametrize("ending", ["normal", "signal-at-spawn", "signal-at-wait", "launch-failure"])
def test_dev_supervisor_restores_handlers_after_owned_cleanup(
    ending: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signals cannot interrupt ownership registration or repeated-signal cleanup."""
    original = dict.fromkeys((signal.SIGINT, signal.SIGTERM, signal.SIGHUP), lambda signum, frame: None)
    handlers = original.copy()
    created = []
    cleaned = []
    forwarded = []

    def install(signum, handler):
        previous = handlers[signum]
        handlers[signum] = handler
        return previous

    def spawn(*args, **kwargs):
        assert kwargs["start_new_session"] is True
        assert handlers != original, "Install cleanup handlers before detaching children"
        if ending == "launch-failure" and created:
            raise OSError("terminal fixture could not launch")
        child = SimpleNamespace(pid=len(created) + 100, returncode=None)
        created.append(child)
        if ending == "signal-at-spawn":
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        return child

    def wait(child, *, stop_requested):
        if ending == "signal-at-wait":
            handlers[signal.SIGTERM](signal.SIGTERM, None)
        assert stop_requested() == ending.startswith("signal-")

    def cleanup(children):
        assert children == created
        cleaned.extend(children)
        if ending.startswith("signal-"):
            # A second signal during TERM/KILL must neither abort cleanup nor
            # replace the first exit reason (SIGINT would incorrectly exit 0).
            handlers[signal.SIGINT](signal.SIGINT, None)
        for child in children:
            child.returncode = 7

    def forward(signum):
        assert cleaned == created
        assert handlers == original
        forwarded.append(signum)

    monkeypatch.setattr(ft, "IS_WINDOWS", False)
    monkeypatch.setattr(ft, "DEV_LOG_DIR", tmp_path)
    monkeypatch.setattr(ft, "resolve_python", lambda: sys.executable)
    monkeypatch.setattr(ft, "provision_workspace", lambda *args: None)
    monkeypatch.setattr(ft, "pnpm_argv", lambda: ["fixture-pnpm"])
    monkeypatch.setattr(ft.subprocess, "Popen", spawn)
    monkeypatch.setattr(ft, "_wait_dev_backend_exit", wait)
    monkeypatch.setattr(ft, "_stop_dev_processes", cleanup)
    monkeypatch.setattr(ft, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, SIGHUP=signal.SIGHUP, SIG_IGN=signal.SIG_IGN,
        getsignal=handlers.__getitem__, signal=install, raise_signal=forward,
    ))
    if ending == "launch-failure":
        with pytest.raises(OSError, match="terminal fixture could not launch"):
            ft.cmd_dev([])
    else:
        assert ft.cmd_dev([]) == (128 + signal.SIGTERM if ending.startswith("signal-") else 7)
    assert created and cleaned == created
    assert handlers == original
    assert forwarded == ([signal.SIGTERM] if ending.startswith("signal-") else [])


@pytest.mark.unit
@pytest.mark.parametrize("already_exited", [False, True])
def test_dev_exit_wait_uses_non_reaping_kqueue_on_python312_macos(
    already_exited: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The older supported macOS Python must retain PID ownership without os.waitid."""
    events = []
    calls = []

    def event(pid, **kwargs):
        events.append((pid, kwargs))
        return "exit-event"

    def control(changes, maximum, timeout):
        calls.append((changes, maximum, timeout))
        if already_exited:
            raise ProcessLookupError("The owned child exited before kevent registration")
        return ["exited"]

    monkeypatch.setattr(ft, "IS_WINDOWS", False)
    monkeypatch.setattr(ft, "os", SimpleNamespace())
    monkeypatch.setattr(ft, "select", SimpleNamespace(
        kqueue=lambda: nullcontext(SimpleNamespace(control=control)), kevent=event,
        KQ_FILTER_PROC=1, KQ_EV_ADD=2, KQ_EV_ONESHOT=4, KQ_NOTE_EXIT=8,
    ))
    child = SimpleNamespace(pid=12345, wait=lambda: pytest.fail("Do not reap a POSIX group leader"))
    ft._wait_dev_backend_exit(child)
    assert events == [(12345, {"filter": 1, "flags": 6, "fflags": 8})]
    assert calls == [(["exit-event"], 1, None)]


@pytest.mark.unit
def test_dev_exit_wait_retains_windows_popen_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    ft._wait_dev_backend_exit(SimpleNamespace(wait=lambda: calls.append(True)))
    assert calls == [True]


@pytest.mark.unit
@pytest.mark.skipif(os.name == "nt", reason="POSIX group ownership")
def test_dev_cleanup_never_signals_a_reaped_leaders_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once wait/poll reaps a root, its PID may be reused and no longer grants group authority."""
    monkeypatch.setattr(ft.os, "killpg", lambda *args: pytest.fail("A reaped PID is not owned group authority"))
    reaped = SimpleNamespace(pid=12345, returncode=7, poll=lambda: 7, wait=lambda **kwargs: 7)
    ft._stop_dev_processes([reaped], timeout=0.01)


@pytest.mark.unit
@pytest.mark.parametrize("taskkill_timeout", [False, True])
def test_windows_dev_cleanup_keeps_bounded_tree_kill_and_reaps_children(
    taskkill_timeout: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows retains /T /F tree cleanup and a bounded fallback if taskkill stalls."""
    calls = []
    waits = []
    kills = []

    def run_tree(argv, **kwargs):
        calls.append(argv)
        assert 0 < kwargs["timeout"] <= 5
        if taskkill_timeout:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return SimpleNamespace(returncode=0)

    def wait(*, timeout):
        waits.append(timeout)
        if taskkill_timeout and len(waits) == 1:
            raise subprocess.TimeoutExpired("fake child", timeout)
        return 0

    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "taskkill" if name == "taskkill" else None)
    monkeypatch.setattr(ft.subprocess, "run", run_tree)
    monkeypatch.setattr(ft.os, "kill", lambda *args: pytest.fail("Must use Windows tree termination"))
    child = SimpleNamespace(pid=12345, poll=lambda: None, wait=wait, kill=lambda: kills.append(True))
    exited = SimpleNamespace(pid=54321, poll=lambda: 7, wait=lambda **kwargs: 7)
    ft._stop_dev_processes([child, exited], timeout=0.1)
    assert calls == [["taskkill", "/PID", "12345", "/T", "/F"]]
    assert waits == ([0.1, 0.1] if taskkill_timeout else [0.1])
    assert kills == ([True] if taskkill_timeout else [])


@pytest.mark.unit
@pytest.mark.parametrize("workers", ["0", "2"])
def test_pytest_does_not_add_xdist_flags_when_plugin_is_missing(
    workers: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Python environment without the optional plugin can still run focused tests."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)

    assert ft.cmd_test_fast(["tests/test_ft_runner.py", "--workers", workers]) == 0
    assert "-n" not in calls[0]
    assert "--workers" not in calls[0]


@pytest.mark.unit
def test_pytest_failure_is_returned_without_starting_rust(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed Python gate must retain its exit code and stop subsequent suites."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 7)

    assert ft.cmd_test(["tests/test_ft_runner.py"]) == 7
    assert len(calls) == 1


@pytest.mark.unit
def test_python_env_joins_pythonpath_with_os_pathsep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hardcoding ``:`` splits Windows drive letters and breaks every import."""
    monkeypatch.setenv("PYTHONPATH", "already-on-the-path")
    env = ft.python_env()

    expected = [str(path) for path in ft.python_package_src_dirs()] + ["already-on-the-path"]
    assert env["PYTHONPATH"] == os.pathsep.join(expected)
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(ft.CORE_SRC)


@pytest.mark.unit
def test_python_env_without_an_existing_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no inherited ``PYTHONPATH`` the workspace source roots are the only entries."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = ft.python_env({"FLINTTRADE_EXTRA": "1"})

    assert env["PYTHONPATH"] == os.pathsep.join(str(path) for path in ft.python_package_src_dirs())
    assert env["FLINTTRADE_EXTRA"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


@pytest.mark.unit
def test_pytest_child_bounds_native_threads_without_changing_production_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the test subprocess gets native limits, including inherited high settings."""
    for variable in _NATIVE_THREAD_VARIABLES:
        monkeypatch.setenv(variable, "64")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-m unit")
    output = tmp_path / "native-environment.json"
    probe = (
        "import json, os, pathlib, sys; "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({name: os.environ.get(name) "
        "for name in sys.argv[2:]}), encoding='utf-8')"
    )
    monkeypatch.setattr(ft, "pytest_argv", lambda flags: [
        sys.executable, "-c", probe, str(output), *_NATIVE_THREAD_VARIABLES, "PYTEST_ADDOPTS",
    ])
    assert ft._run_pytest(["--workers", "0"]) == 0
    child = json.loads(output.read_text(encoding="utf-8"))
    assert {name: child[name] for name in _NATIVE_THREAD_VARIABLES} == dict.fromkeys(_NATIVE_THREAD_VARIABLES, "1")
    assert child["PYTEST_ADDOPTS"] == "-m unit", "Interactive focused options remain available"
    production = ft.python_env()
    assert {name: production[name] for name in _NATIVE_THREAD_VARIABLES} == dict.fromkeys(_NATIVE_THREAD_VARIABLES, "64")
    assert production["PYTEST_ADDOPTS"] == "-m unit"


@pytest.mark.unit
def test_python_env_exposes_every_workspace_package() -> None:
    """``flinttrade_core.app`` eagerly imports its siblings, so core alone is not enough.

    The no-uv ``setup`` fallback installs ``requirements.lock``, which is exported
    with ``--no-emit-workspace`` and therefore contains no ``flinttrade_*``
    distribution at all. If the child ``PYTHONPATH`` carried only the core source
    tree, ``start`` would die on ``import flinttrade_data`` right after ``setup``
    reported success.
    """
    entries = ft.python_env()["PYTHONPATH"].split(os.pathsep)
    declared = {
        init.parent.parent
        for init in ft.REPO_ROOT.glob("packages/*/*/src/flinttrade_*/__init__.py")
    }

    assert declared, "no workspace Python packages were discovered"
    assert {str(path) for path in declared} <= set(entries)
    assert "flinttrade_data" in ft.workspace_module_names()
    assert entries[0] == str(ft.CORE_SRC), "flinttrade_core must resolve first"


@pytest.mark.unit
def test_setup_refuses_to_report_success_for_an_unrunnable_environment() -> None:
    """``cmd_setup`` must verify importability before printing 'Next steps'.

    A setup that reports OK and leaves an environment whose very next command
    dies with ``ModuleNotFoundError`` is worse than one that fails outright.
    """
    source = _FT_PATH.read_text(encoding="utf-8")
    body = re.search(r"^def cmd_setup\(.*?^def ", source, flags=re.MULTILINE | re.DOTALL)
    assert body is not None, "scripts/ft.py no longer defines cmd_setup()"

    gate = body.group(0).find("missing_workspace_modules(")
    next_steps = body.group(0).find("Next steps:")
    assert gate != -1, "cmd_setup must probe the workspace packages before claiming success"
    assert next_steps != -1
    assert gate < next_steps, "the importability gate must run before setup advertises success"
    assert "return 1" in body.group(0)


@pytest.mark.unit
def test_quiet_runs_never_discard_stderr() -> None:
    """A quiet step that fails must still say why — silence reads as a hang."""
    source = _FT_PATH.read_text(encoding="utf-8")
    run_body = re.search(r"^def run\(.*?^def capture\(", source, flags=re.MULTILINE | re.DOTALL)
    assert run_body is not None, "scripts/ft.py no longer defines run() before capture()"

    call = re.search(r"stderr=(\S+?),", run_body.group(0))
    assert call is not None
    assert call.group(1) == "None", (
        "run(quiet=True) must suppress stdout only; discarding stderr hides first-run failures"
    )


@pytest.mark.unit
def test_first_run_provisioning_reports_its_own_failure() -> None:
    """``provision_workspace`` must print actionable text before aborting."""
    assert callable(ft.provision_workspace)
    source = _FT_PATH.read_text(encoding="utf-8")
    for handler in ("def cmd_start(", "def cmd_dev(", "def cmd_setup("):
        start = source.index(handler)
        body = source[start : source.index("\ndef ", start + 1)]
        assert "provision_workspace(" in body, f"{handler.strip('def (')} bypasses provision_workspace"
        assert "--provision-master-password" not in body, (
            f"{handler.strip('def (')} still calls the init step directly instead of via provision_workspace"
        )


# ---------------------------------------------------------------------------
# Stdlib-only guarantee
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ft_imports_nothing_outside_the_standard_library() -> None:
    """The first-run import closure stays dependency-free, including its helper."""
    _assert_bootstrap_stdlib_only((_FT_PATH, _BOOTSTRAP_HELPER_PATH, _LOCAL_CHECKS_PATH, _CHANGE_CLASSIFIER_PATH))


@pytest.mark.unit
def test_check_loads_exact_sibling_helpers_from_a_foreign_cwd(tmp_path: Path) -> None:
    """Unrelated check helpers on PYTHONPATH cannot hide required checks."""
    for name in ("check_local.py", "check_changes.py"):
        (tmp_path / name).write_text("raise RuntimeError('shadow helper imported')\n", encoding="utf-8")
    loader = (
        "import importlib.util, pathlib, sys\n"
        "path = pathlib.Path(sys.argv[1])\n"
        "spec = importlib.util.spec_from_file_location('unregistered_ft_name', path)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "raise SystemExit(module.main(['check', '--full', '--dry-run', '--workers', '0']))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", loader, str(_FT_PATH)], cwd=tmp_path,
        env=os.environ | {"PYTHONPATH": str(tmp_path)}, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Gate: full" in result.stdout
    assert "scripts/__tests__" in result.stdout
    assert "Dry run only; no check results." in result.stdout


@pytest.mark.unit
def test_invalid_worker_override_never_starts_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed worker count must fail before any expensive subprocess starts."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test_fast(["--workers", "-1"]) == 2
    assert not calls


@pytest.mark.unit
@pytest.mark.parametrize("workers", [[], ["--workers", "0"]])
def test_existing_pytest_xdist_option_wins_without_duplicate_workers(
    workers: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit pytest -n remains usable and must not conflict with the default."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    monkeypatch.setenv("FLINTTRADE_TEST_WORKERS", "invalid-but-unused")
    assert ft.cmd_test_fast(["tests/test_ft_runner.py", *workers, "-n", "1"]) == 0
    assert calls[0].count("-n") == 1
    assert calls[0][calls[0].index("-n") + 1] == "1"


@pytest.mark.unit
@pytest.mark.parametrize("disable", [["-p", "no:xdist"], ["-pno:xdist"]])
@pytest.mark.parametrize("workers", [[], ["--workers", "0"], ["--workers", "2"]])
def test_explicitly_disabled_xdist_suppresses_automatic_workers(
    disable: list[str], workers: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed xdist must not add unsupported -n after the caller disables its plugin."""
    probes = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: probes.append(args) or "")
    argv = ft.pytest_argv(["tests/test_ft_runner.py", *disable, *workers])
    assert "-n" not in argv
    assert all(arg in argv for arg in disable)
    assert not probes, "An explicit disable does not need a plugin availability probe"


@pytest.mark.unit
@pytest.mark.parametrize("disable", [["-p", "no:xdist"], ["-pno:xdist"]])
def test_explicit_worker_flags_remain_user_controlled_with_disabled_xdist(
    disable: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forward an explicitly incompatible -n unchanged so pytest gives its own error."""
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    argv = ft.pytest_argv(["tests/test_ft_runner.py", *disable, "-n", "1"])
    assert argv.count("-n") == 1
    assert argv[argv.index("-n") + 1] == "1"
    assert all(arg in argv for arg in disable)


@pytest.mark.unit
@pytest.mark.parametrize("disable", [["-p", "no:xdist"], ["-pno:xdist"]])
def test_disabled_xdist_command_collects_real_tests_without_invalid_worker_flags(
    disable: list[str], tmp_path: Path
) -> None:
    """Exercise pytest's real plugin/argument handling without running a test suite."""
    target = tmp_path / "test_sample.py"
    target.write_text("def test_example(): assert False, 'collection must not execute this'\n", encoding="utf-8")
    configuration = tmp_path / "pytest.ini"
    configuration.write_text("[pytest]\n", encoding="utf-8")
    argv = ft.pytest_argv([
        str(target), *disable, "--collect-only", "-q", "-c", str(configuration), f"--confcutdir={tmp_path}",
    ])
    result = subprocess.run(
        argv, cwd=tmp_path, env=ft.pytest_env({"PYTEST_ADDOPTS": ""}),
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sample.py::test_example" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("explicit_config", [
    ["-c", "configuration/custom.toml"], ["-cconfiguration/custom.toml"],
    ["--config-file", "configuration/custom.toml"], ["--config-file=configuration/custom.toml"],
])
def test_explicit_pytest_configuration_remains_authoritative(
    explicit_config: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    argv = ft.pytest_argv(["packages/core/core/tests", *explicit_config, "--workers", "0"])
    assert str(ft.REPO_ROOT / "pyproject.toml") not in argv
    assert all(option in argv for option in explicit_config)


@pytest.mark.unit
def test_focused_nested_package_keeps_root_isolation_configuration_and_nodeids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Focused feedback must use the same root fixture/config/node ID as full collection."""
    root_config = tmp_path / "pyproject.toml"
    root_config.write_text('[tool.pytest.ini_options]\nconsider_namespace_packages = true\n', encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import os, pytest\n"
        "@pytest.fixture(autouse=True)\n"
        "def root_workspace(monkeypatch, tmp_path):\n"
        "    monkeypatch.setenv('FLINTTRADE_WORKSPACE_DIR', str(tmp_path / 'root-isolated'))\n",
        encoding="utf-8",
    )
    package = tmp_path / "packages" / "services" / "sample"
    target = package / "tests" / "test_boundary.py"
    target.parent.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nconsider_namespace_packages = false\n', encoding="utf-8",
    )
    nodeid = "packages/services/sample/tests/test_boundary.py::test_root_context"
    target.write_text(
        "import os\n"
        "def test_root_context(request):\n"
        "    assert request.config.getini('consider_namespace_packages') is True\n"
        "    assert os.environ['FLINTTRADE_WORKSPACE_DIR'].endswith('root-isolated')\n"
        f"    assert request.node.nodeid == {nodeid!r}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ft, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ft, "resolve_python", lambda: sys.executable)
    for flags in (["--collect-only", "-q"], [str(target), "--collect-only", "-q"], [str(target), "-q"]):
        argv = ft.pytest_argv([*flags, "--workers", "0"])
        result = subprocess.run(
            argv, cwd=tmp_path, env=ft.pytest_env({"PYTEST_ADDOPTS": ""}),
            capture_output=True, text=True, check=False, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if "--collect-only" in flags:
            assert nodeid in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("disable_source", ["environment", "option"])
@pytest.mark.parametrize("plugins", [[], ["-p", "xdist"], ["-pxdist.plugin"]])
def test_plugin_autoload_disable_keeps_timeout_and_respects_explicit_xdist(
    disable_source: str, plugins: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Autoload control remains usable without introducing unsupported worker/watchdog flags."""
    target = tmp_path / "test_sample.py"
    target.write_text("def test_example(): assert False, 'collect only'\n", encoding="utf-8")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    if disable_source == "environment":
        monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        options = []
    else:
        monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
        options = ["--disable-plugin-autoload"]
    argv = ft.pytest_argv([str(target), *options, *plugins, "--collect-only", "-q", "-c", str(config)])
    assert ("-n" in argv) == bool(plugins)
    result = subprocess.run(
        argv, cwd=tmp_path, env=ft.pytest_env({"PYTEST_ADDOPTS": ""}),
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sample.py::test_example" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("module_name", ["xdist", "xdist.plugin", "pytest_timeout", "timeout"])
def test_autoload_disabled_environment_plugin_specs_load_modules_without_entrypoint_aliases(
    module_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PYTEST_PLUGINS imports modules; hookless aliases cannot register worker/watchdog flags."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTEST_PLUGINS", module_name)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    # A module named timeout may exist, but it is distinct from pytest's
    # entry-point alias. Supply a hookless one to exercise that boundary.
    (tmp_path / "timeout.py").write_text("# no pytest hooks\n", encoding="utf-8")
    target = tmp_path / "test_sample.py"
    target.write_text("def test_example(): assert False, 'collection only'\n", encoding="utf-8")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    argv = ft.pytest_argv([str(target), "--collect-only", "-q", "-c", str(config)])
    assert ("-n" in argv) == (module_name == "xdist.plugin")
    assert "--timeout-method=thread" in argv
    assert ("pytest_timeout" in argv) == (module_name != "pytest_timeout")
    result = subprocess.run(
        argv, cwd=tmp_path, env=ft.pytest_env({"PYTEST_ADDOPTS": ""}),
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sample.py::test_example" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("plugin", ["timeout", "pytest_timeout"])
def test_autoload_disabled_cli_timeout_alias_and_module_keep_the_watchdog(
    plugin: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI -p can resolve either the timeout entry point or its real hook module."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    target = tmp_path / "test_sample.py"
    target.write_text("def test_example(): assert False, 'collection only'\n", encoding="utf-8")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    argv = ft.pytest_argv([str(target), "-p", plugin, "--collect-only", "-q", "-c", str(config)])
    assert argv.count("-p") == 1, "An explicitly loaded watchdog must not be injected again"
    assert "--timeout-method=thread" in argv
    assert "-n" not in argv
    result = subprocess.run(
        argv, cwd=tmp_path, env=ft.pytest_env({"PYTEST_ADDOPTS": ""}),
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sample.py::test_example" in result.stdout


@pytest.mark.unit
@pytest.mark.parametrize("disable", [["-p", "no:timeout"], ["-pno:pytest_timeout"]])
def test_disabling_the_mandatory_timeout_plugin_fails_before_test_execution(
    disable: list[str], monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    calls = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(argv) or 0)
    assert ft.cmd_test_fast(["tests/test_ft_runner.py", *disable]) == 2
    assert not calls
    assert "requires pytest-timeout" in capsys.readouterr().err


@pytest.mark.unit
def test_pytest_worker_environment_override_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Developer worker preferences must affect the selected interpreter's pytest command."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: "")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    monkeypatch.setenv("FLINTTRADE_TEST_WORKERS", "2")
    assert ft.cmd_test_fast(["tests/test_ft_runner.py"]) == 0
    assert calls[0][calls[0].index("-n") + 1] == "2"


@pytest.mark.unit
def test_option_values_do_not_drop_package_suites(monkeypatch: pytest.MonkeyPatch) -> None:
    """An output prefix is a flag value, not an implicit request to run only root tests."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test_fast(["--junit-prefix", "feedback"]) == 0
    assert "packages/core/core/tests" in calls[0]
    assert "scripts/__tests__" in calls[0]


@pytest.mark.unit
def test_path_like_option_values_do_not_drop_package_suites(monkeypatch: pytest.MonkeyPatch) -> None:
    """An output prefix containing a slash must not silently select only root tests."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test_fast(["--junit-prefix", "test/results"]) == 0
    assert "packages/core/core/tests" in calls[0]
    assert "scripts/__tests__" in calls[0]


@pytest.mark.unit
def test_pytest_separator_keeps_runner_bounds_before_positional_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    """A positional separator must not turn -x, xdist or watchdog options into filenames."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: "")
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test_fast(["--", "tests/test_ft_runner.py"]) == 0
    command = calls[0]
    separator = command.index("--")
    assert command[separator + 1:] == ["tests/test_ft_runner.py"]
    assert command.index("-x") < separator
    assert command.index("-n") < separator
    assert command.index("--timeout-method=thread") < separator


@pytest.mark.unit
@pytest.mark.parametrize("options", [
    ["-W", "ignore::DeprecationWarning"],
    ["--pythonwarnings", "ignore::DeprecationWarning"],
    ["--config-file", "configuration/test.toml"],
    ["--log-file-format", "tests/%(message)s::%(levelname)s"],
    ["--log-file-date-format", "tests/%Y"],
    ["--doctest-glob", "docs/*.md"],
    ["--junitprefix", "tests/feedback"],
    ["--debug", "tests/debug.log"],
    ["--cache-show", "tests/*"],
    ["--tx", "popen//python=python3"],
    ["--px", "id=proxy//popen"],
    ["--testrunuid", "tests/feedback"],
    ["--log-disable", "flinttrade/tests"],
])
def test_warning_log_and_config_values_do_not_omit_default_package_roots(
    options: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pytest option values containing paths or :: must not silently narrow the suite."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test_fast(options) == 0
    assert "packages/core/core/tests" in calls[0]
    assert "scripts/__tests__" in calls[0]
    assert all(option in calls[0] for option in options)


@pytest.mark.unit
@pytest.mark.parametrize("target", ["tests/missing.py::test_missing", "missing.py::test_missing"])
def test_malformed_explicit_python_targets_are_forwarded_without_expanding_suites(
    target: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid explicit node IDs must retain pytest's error instead of turning into a full run."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 4)
    assert ft.cmd_test_fast([target]) == 4
    assert target in calls[0]
    assert "packages/core/core/tests" not in calls[0]


@pytest.mark.unit
def test_warning_clause_alone_is_not_a_python_nodeid() -> None:
    """A non-path warning filter must not be accepted solely because it contains ::."""
    assert not ft._pytest_has_targets(["ignore::DeprecationWarning"])


@pytest.mark.unit
@pytest.mark.parametrize("options", [
    ["-q"], ["--durations", "10"], ["-W", "ignore::DeprecationWarning"], ["--workers", "2"],
])
def test_test_command_keeps_rust_when_pytest_options_do_not_select_a_subset(
    options: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing Python output/warnings/workers must not omit the Rust half of the default test command."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "_run_pytest", lambda _flags: 0)
    monkeypatch.setattr(ft, "resolve_python", lambda: "/repo/.venv/bin/python")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "cargo" if name == "cargo" else None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test(options) == 0
    assert calls == [["cargo", "test", "--manifest-path", "packages/core/ticks/Cargo.toml"]]


@pytest.mark.unit
@pytest.mark.parametrize("selection", [
    ["tests/test_ft_runner.py"], ["-k", "workspace"], ["-m", "unit"], ["--collect-only"],
    ["--collectonly"], ["--markers"], ["--setuponly"], ["--setupplan"], ["--setup-plan"],
    ["--cache-show"], ["-V"], ["--sw-reset"], ["--stepwise-reset"],
    ["--lf"], ["--ignore=packages/services/ai/tests"], ["--ft-shard-index=0", "--ft-shard-count=4"],
])
def test_test_command_avoids_rust_when_python_tests_are_selected_or_not_executed(
    selection: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Focused, replay and collection-only feedback must not start unrelated compilation."""
    calls: list[list[str]] = []
    monkeypatch.setattr(ft, "_run_pytest", lambda _flags: 0)
    monkeypatch.setattr(ft.shutil, "which", lambda name: "cargo" if name == "cargo" else None)
    monkeypatch.setattr(ft, "run", lambda argv, **kwargs: calls.append(list(argv)) or 0)
    assert ft.cmd_test(selection) == 0
    assert not calls


@pytest.mark.unit
@pytest.mark.parametrize("system, variable, library", [
    ("Linux", "LD_LIBRARY_PATH", "libpython3.13.so.1.0"),
    ("Darwin", "DYLD_LIBRARY_PATH", "libpython3.13.dylib"),
])
def test_rust_test_environment_preserves_loader_paths_for_the_selected_interpreter(
    system: str, variable: str, library: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PyO3-linked tests need uv's libpython directory without dropping existing loader paths."""
    assert hasattr(ft, "rust_test_env"), "the selected interpreter's shared library path must reach Rust tests"
    libdir = tmp_path / "managed-python" / "lib"
    libdir.mkdir(parents=True)
    (libdir / library).touch()
    probes: list[list[str]] = []
    monkeypatch.setattr(ft.platform, "system", lambda: system)
    monkeypatch.setenv(variable, "existing-loader-path")
    monkeypatch.setattr(ft, "capture", lambda argv, **kwargs: probes.append(list(argv)) or str(libdir))
    python = "/managed-venv/bin/python"

    env = ft.rust_test_env(python)
    assert env["PYO3_PYTHON"] == python
    assert env[variable] == str(libdir) + ":existing-loader-path"
    assert probes[0][:3] == [python, "-I", "-c"]


@pytest.mark.unit
def test_rust_test_environment_does_not_probe_unix_loader_paths_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows Rust tests retain their interpreter pin without Unix loader overrides."""
    assert hasattr(ft, "rust_test_env"), "Rust tests need a platform-aware environment"
    monkeypatch.setattr(ft.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ft, "capture", lambda *args, **kwargs: pytest.fail("Windows must not probe LIBDIR"))
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("DYLD_LIBRARY_PATH", raising=False)
    env = ft.rust_test_env("C:/repo/.venv/Scripts/python.exe")
    assert env["PYO3_PYTHON"] == "C:/repo/.venv/Scripts/python.exe"
    assert "LD_LIBRARY_PATH" not in env
    assert "DYLD_LIBRARY_PATH" not in env


def _assert_bootstrap_stdlib_only(paths: tuple[Path, ...]) -> None:
    """Reject imports outside the standard library from each first-run module."""
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots: set[str] = set()
        relative: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    relative.append(f"line {node.lineno}")
                    continue
                roots.add((node.module or "").split(".")[0])

        label = path.name
        assert not relative, f"{label} cannot use relative imports: {relative}"
        third_party = sorted(root for root in roots if root and root not in allowed)
        assert not third_party, f"{label} must stay stdlib-only; found: {third_party}"
        assert not any(root.startswith("flinttrade") for root in roots), (
            f"{label} must not import flinttrade packages during first-run setup"
        )


@pytest.mark.unit
def test_bootstrap_stdlib_contract_rejects_a_temporary_forbidden_import(tmp_path: Path) -> None:
    """The import guard detects a third-party dependency in any bootstrap module."""
    injected_helper = tmp_path / "broker_sdk_environment.py"
    injected_helper.write_text("import requests\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=r"broker_sdk_environment.py.*requests"):
        _assert_bootstrap_stdlib_only((_FT_PATH, injected_helper))


@pytest.mark.unit
def test_bootstrap_loader_registers_reuses_and_avoids_unrelated_module_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper is importable during execution and repeated loads reuse it safely."""
    module_name = "_test_flinttrade_bootstrap_helper"
    unrelated = ModuleType(module_name)
    unrelated.__file__ = str(tmp_path / "unrelated.py")
    monkeypatch.setitem(sys.modules, module_name, unrelated)

    helper_path = tmp_path / "bootstrap_helper.py"
    helper_path.write_text(
        "import sys\n"
        "assert sys.modules[__name__].__file__ == __file__\n"
        "EXECUTIONS = 1\n",
        encoding="utf-8",
    )

    loaded = ft._load_module_from_path(module_name, helper_path)
    loaded_again = ft._load_module_from_path(module_name, helper_path)

    assert loaded is loaded_again
    assert loaded.EXECUTIONS == 1
    assert loaded.__name__ == f"{module_name}_1"
    assert sys.modules[module_name] is unrelated
    assert sys.modules[loaded.__name__] is loaded


@pytest.mark.unit
def test_bootstrap_loader_rolls_back_registration_when_execution_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed helper execution removes its partial entry but preserves collisions."""
    module_name = "_test_flinttrade_failing_bootstrap_helper"
    unrelated = ModuleType(module_name)
    unrelated.__file__ = str(tmp_path / "unrelated.py")
    monkeypatch.setitem(sys.modules, module_name, unrelated)

    helper_path = tmp_path / "failing_helper.py"
    helper_path.write_text(
        "import sys\n"
        "assert sys.modules[__name__].__file__ == __file__\n"
        "raise RuntimeError('intentional fixture failure')\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="intentional fixture failure"):
        ft._load_module_from_path(module_name, helper_path)

    assert sys.modules[module_name] is unrelated
    assert f"{module_name}_1" not in sys.modules
