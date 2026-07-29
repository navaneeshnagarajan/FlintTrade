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

Everything here is hermetic: ``Path.home`` and the workspace env vars are
redirected into ``tmp_path``, no command is really executed, and no network or
real home directory is touched.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import platform
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

from flinttrade_core import workspace as core_workspace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FT_PATH = _REPO_ROOT / "scripts" / "ft.py"
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
    """``ft.py`` runs before any dependency exists — including ``flinttrade_core``."""
    tree = ast.parse(_FT_PATH.read_text(encoding="utf-8"), filename=str(_FT_PATH))

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

    assert not relative, f"scripts/ft.py is a standalone script and cannot use relative imports: {relative}"

    allowed = set(sys.stdlib_module_names) | {"__future__"}
    third_party = sorted(root for root in roots if root and root not in allowed)
    assert not third_party, f"scripts/ft.py must stay stdlib-only; found: {third_party}"
    assert not any(root.startswith("flinttrade") for root in roots), (
        "scripts/ft.py must not import flinttrade_core - it runs before the packages are installed"
    )
