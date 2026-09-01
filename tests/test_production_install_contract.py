"""Source-pin for the production systemd install contract.

``docs/setup/linux.md`` tells operators to run ``infra/scripts/setup-production.sh``,
which copies ``infra/systemd/flinttrade.service`` into systemd. Those two files
plus ``requirements.lock`` must agree so a first-time Ubuntu host can start.

Expected contract — this module is the tracking pin. Development implements the
product fix on this same branch; do not weaken these assertions to match the
broken installer or unit.

* install prefix ``/opt/flinttrade`` (hardcoded; matches the unit)
* installer creates a repo-local ``.venv``
* hashed lock includes waitress (``python -m flinttrade_core.app``)
* unit sets ``FLINTTRADE_BACKEND_PORT`` (the name ``flinttrade_core.app`` reads)
* unit sets ``FLINTTRADE_WORKSPACE_DIR`` inside ``ReadWritePaths``
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from flinttrade_core.workspace import Workspace

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INSTALLER = _REPO_ROOT / "infra" / "scripts" / "setup-production.sh"
_DEPLOY = _REPO_ROOT / "infra" / "scripts" / "deploy.sh"
_CONTRACT = _REPO_ROOT / "infra" / "scripts" / "production-contract.sh"
_UNIT = _REPO_ROOT / "infra" / "systemd" / "flinttrade.service"
_LOCK = _REPO_ROOT / "requirements.lock"
_APP = _REPO_ROOT / "packages" / "core" / "core" / "src" / "flinttrade_core" / "app.py"
_PRODUCTION_PREFIX = "/opt/flinttrade"

_VENV_CREATE_RE = re.compile(r'(?:python3(?:\.\d+)?|"?\$PYTHON_BIN"?) -m venv')
_GUNICORN_LOCK_RE = re.compile(r"(?m)^gunicorn==")


@pytest.mark.unit
def test_production_installer_defaults_to_systemd_prefix() -> None:
    """setup-production.sh must install where flinttrade.service already looks.

    The unit's WorkingDirectory, FLINTTRADE_HOME, EnvironmentFile, ExecStart
    and ReadWritePaths are all ``/opt/flinttrade``. A default of
    ``$HOME/FlintTrade`` leaves the copied unit pointing at a tree the
    installer never created.
    """
    installer = _INSTALLER.read_text(encoding="utf-8")
    unit = _UNIT.read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/flinttrade" in unit
    assert "Environment=FLINTTRADE_HOME=/opt/flinttrade" in unit
    assert "flinttrade_production_prefix" in installer
    assert "flinttrade_assert_no_dir_override" in installer
    assert "flinttrade_assert_safe_install_dir" in installer
    assert 'INSTALL_DIR="${FLINTTRADE_DIR:-' not in installer
    assert "FLINTTRADE_DIR:-/opt/flinttrade" not in installer


@pytest.mark.unit
def test_production_installer_creates_unit_venv() -> None:
    """The installer must create the ``.venv`` the unit ExecStart's.

    Apt-installing ``python3-venv`` is not enough: the script must run
    ``python3 -m venv`` (or ``python3.x -m venv``) at the install prefix.
    Optional ``uv sync`` when uv happens to be on PATH does not satisfy this.
    """
    installer = _INSTALLER.read_text(encoding="utf-8")
    creates_venv = _VENV_CREATE_RE.search(installer) is not None
    mentions_venv_dir = ".venv" in installer

    assert creates_venv, (
        "setup-production.sh must create $INSTALL_DIR/.venv via python3 -m venv; "
        "flinttrade.service starts /opt/flinttrade/.venv/bin/python -m flinttrade_core.app"
    )
    assert mentions_venv_dir, "setup-production.sh must name the unit venv path .venv"


@pytest.mark.unit
def test_requirements_lock_pins_waitress_not_gunicorn() -> None:
    """The hashed lock must provide Waitress, the supported backend server.

    ``python -m flinttrade_core.app`` serves with Waitress. gunicorn/eventlet
    is not the production runtime for this asyncio/httpx/duckdb app.
    """
    lock = _LOCK.read_text(encoding="utf-8")
    unit = _UNIT.read_text(encoding="utf-8")
    has_waitress = re.search(r"(?m)^waitress==", lock) is not None

    assert "gunicorn" not in unit
    assert "eventlet" not in unit
    assert not _GUNICORN_LOCK_RE.search(lock), "requirements.lock must not pin gunicorn for this unit"
    assert has_waitress, "requirements.lock must pin waitress==… (the runtime flinttrade_core.app uses)"


@pytest.mark.unit
def test_systemd_unit_sets_backend_port_env() -> None:
    """The unit must export the env name the backend actually reads.

    ``flinttrade_core.app._resolve_backend_port`` reads
    ``FLINTTRADE_BACKEND_PORT``. ``FLINTTRADE_PORT`` is a legacy alias only
    Docker's start helper honours. A production unit that sets the legacy
    name does not configure the backend.
    """
    unit = _UNIT.read_text(encoding="utf-8")
    app = _APP.read_text(encoding="utf-8")
    port_envs = [
        line
        for line in unit.splitlines()
        if line.startswith("Environment=FLINTTRADE_") and "PORT" in line
    ]
    sets_backend_port = any(line.startswith("Environment=FLINTTRADE_BACKEND_PORT=") for line in port_envs)

    assert 'os.environ.get("FLINTTRADE_BACKEND_PORT"' in app
    assert sets_backend_port, (
        "flinttrade.service must set Environment=FLINTTRADE_BACKEND_PORT=… "
        f"(not only the legacy FLINTTRADE_PORT name); found {port_envs}"
    )


def _unit_environment(text: str) -> dict[str, str]:
    """Return ``Environment=KEY=value`` assignments from a systemd unit."""
    env: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("Environment="):
            continue
        payload = line[len("Environment=") :]
        if "=" not in payload:
            continue
        key, _, value = payload.partition("=")
        env[key] = value
    return env


def _readwrite_paths(text: str) -> list[str]:
    """Return the unit's ``ReadWritePaths`` entries."""
    for line in text.splitlines():
        if line.startswith("ReadWritePaths="):
            return line[len("ReadWritePaths=") :].split()
    return []


def _remap_production_path(path: str, local_prefix: Path) -> Path:
    """Map a hardcoded ``/opt/flinttrade`` path onto a tempdir prefix."""
    if path == _PRODUCTION_PREFIX:
        return local_prefix
    nested = _PRODUCTION_PREFIX + "/"
    assert path.startswith(nested), f"{path!r} is not under {_PRODUCTION_PREFIX}"
    return local_prefix.joinpath(*path[len(nested) :].split("/"))


def _assert_inside_writable(path: Path, writable: list[Path]) -> None:
    """Fail unless ``path`` is one of ``writable`` or a descendant."""
    resolved = path.resolve()
    roots = [root.resolve() for root in writable]
    if any(resolved == root or root in resolved.parents for root in roots):
        return
    raise AssertionError(f"{resolved} is outside ReadWritePaths {roots}")


@pytest.mark.unit
def test_workspace_runtime_writes_stay_inside_unit_readwrite_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workspace.json, logs and archive must land under the unit ReadWritePaths.

    ``ProtectSystem=strict`` makes the tree read-only except ``ReadWritePaths``.
    Setting only ``FLINTTRADE_HOME=/opt/flinttrade`` makes Workspace write
    ``workspace.json`` at the code root, which systemd will deny.
    """
    unit = _UNIT.read_text(encoding="utf-8")
    env = _unit_environment(unit)
    declared = _readwrite_paths(unit)
    assert declared, "flinttrade.service must declare ReadWritePaths"

    local_prefix = tmp_path / "opt" / "flinttrade"
    local_prefix.mkdir(parents=True)
    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
    if "FLINTTRADE_WORKSPACE_DIR" in env:
        monkeypatch.setenv(
            "FLINTTRADE_WORKSPACE_DIR",
            str(_remap_production_path(env["FLINTTRADE_WORKSPACE_DIR"], local_prefix)),
        )
    if "FLINTTRADE_HOME" in env:
        monkeypatch.setenv(
            "FLINTTRADE_HOME",
            str(_remap_production_path(env["FLINTTRADE_HOME"], local_prefix)),
        )

    writable = [_remap_production_path(path, local_prefix) for path in declared]
    for path in writable:
        path.mkdir(parents=True, exist_ok=True)

    workspace = Workspace()
    workspace.initialise()
    for path in (
        workspace.config_path,
        workspace.log_dir,
        workspace.archive_dir,
        workspace.fast_data_dir,
    ):
        _assert_inside_writable(path, writable)


def _bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet and return the completed process."""
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=merged,
        cwd=_REPO_ROOT,
        timeout=10,
        check=False,
    )


def _write_executable(path: Path, body: str) -> None:
    """Write ``body`` and mark ``path`` executable."""
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.mark.unit
def test_python_floor_rejects_interpreter_below_3_12(tmp_path: Path) -> None:
    """setup-production must refuse Python < 3.12 before creating the unit venv."""
    fake = tmp_path / "python3"
    _write_executable(fake, "#!/bin/bash\nexit 1\n")
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_python_floor {fake.as_posix()}",
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "3.12" in combined


@pytest.mark.unit
def test_python_floor_accepts_interpreter_at_or_above_3_12() -> None:
    """The live interpreter (CI/dev is 3.12+) must pass the Ubuntu floor."""
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_python_floor {shlex.quote(sys.executable)}",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_production_scripts_parse_under_bash_n() -> None:
    """Installer, deploy and the shared contract must be valid bash."""
    for path in (_CONTRACT, _INSTALLER, _DEPLOY):
        parsed = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert parsed.returncode == 0, f"{path.name}: {parsed.stderr}"


@pytest.mark.unit
def test_production_installer_checks_python_floor_before_venv() -> None:
    """The Ubuntu installer must run the 3.12 floor before ``python3 -m venv``."""
    installer = _INSTALLER.read_text(encoding="utf-8")
    assert "production-contract.sh" in installer
    match = _VENV_CREATE_RE.search(installer)
    assert match is not None, "setup-production.sh must create the unit venv"
    before = installer[: match.start()]
    assert "flinttrade_assert_python_floor" in before, (
        "setup-production.sh must call flinttrade_assert_python_floor before venv creation"
    )


def _backslash_continued_commands(text: str, token: str) -> list[str]:
    """Return joined commands that mention ``token``, including ``\\`` continuations."""
    commands: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if current:
            current.append(stripped)
            if not stripped.endswith("\\"):
                commands.append("\n".join(current))
                current = []
            continue
        if token in stripped and not stripped.lstrip().startswith("#"):
            if stripped.endswith("\\"):
                current = [stripped]
            else:
                commands.append(stripped)
    if current:
        commands.append("\n".join(current))
    return commands


@pytest.mark.unit
def test_production_installer_chowns_only_runtime_paths() -> None:
    """www-data may own workspace/data/log paths, never the code/.git/.venv tree."""
    installer = _INSTALLER.read_text(encoding="utf-8")
    chowns = _backslash_continued_commands(installer, "chown")
    assert chowns, "setup-production.sh must chown runtime paths for www-data"
    prefix_reclaim = 'sudo chown -R "root:$SERVICE_USER" "$INSTALL_DIR"'
    assert any(prefix_reclaim in block for block in chowns), (
        "setup-production.sh must reclaim a legacy non-root checkout to root:www-data "
        "before chmod/chgrp so sudo git deploys do not hit dubious ownership"
    )
    for block in chowns:
        if prefix_reclaim in block:
            continue
        assert not re.search(r'"\$INSTALL_DIR"(?!/)', block), (
            "do not chown -R the entire install prefix to the service user; keep code root-owned. "
            f"found: {block}"
        )
        if "$INSTALL_DIR/.env" in block:
            assert block == 'sudo chown "root:$SERVICE_USER" "$INSTALL_DIR/.env"'
            continue
        assert "$INSTALL_DIR/data" in block or '"$INSTALL_DIR/data"' in block
        assert "$INSTALL_DIR/.flinttrade" in block or '"$INSTALL_DIR/.flinttrade"' in block


@pytest.mark.unit
def test_production_contract_rejects_flinttrade_dir_override() -> None:
    """The unit is hardcoded to /opt/flinttrade; FLINTTRADE_DIR must not relocate it."""
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_no_dir_override",
        env={**os.environ, "FLINTTRADE_DIR": "/tmp/elsewhere"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "/opt/flinttrade" in combined


@pytest.mark.unit
def test_safe_install_dir_rejects_symlink_and_nongit(tmp_path: Path) -> None:
    """Pre-existing symlink targets and non-git trees must not be adopted."""
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(target)
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_safe_install_dir {link.as_posix()}",
    )
    assert result.returncode != 0
    assert "symlink" in (result.stdout + result.stderr).lower()

    nongit = tmp_path / "nongit"
    nongit.mkdir()
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_safe_install_dir {nongit.as_posix()}",
    )
    assert result.returncode != 0
    assert "git" in (result.stdout + result.stderr).lower()


@pytest.mark.unit
def test_safe_install_dir_allows_missing_or_git_trees(tmp_path: Path) -> None:
    """A missing prefix may be cloned; an existing git checkout may be reused."""
    missing = tmp_path / "absent"
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_safe_install_dir {missing.as_posix()}",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    git_dir = tmp_path / "repo"
    git_dir.mkdir()
    (git_dir / ".git").mkdir()
    result = _bash(
        f"source {_CONTRACT.as_posix()} && flinttrade_assert_safe_install_dir {git_dir.as_posix()}",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.unit
def test_deploy_updates_root_owned_install_without_taking_ownership() -> None:
    """deploy.sh must update a root-owned /opt/flinttrade and leave ownership alone."""
    deploy = _DEPLOY.read_text(encoding="utf-8")
    assert "production-contract.sh" in deploy
    assert "flinttrade_assert_no_dir_override" in deploy
    assert "flinttrade_assert_safe_install_dir" in deploy
    assert "flinttrade_production_prefix" in deploy
    assert "FLINTTRADE_DIR:-" not in deploy
    assert "sudo git" in deploy
    assert 'safe.directory=$REPO_DIR' in deploy
    assert deploy.count('git -c "safe.directory=$REPO_DIR"') >= 2
    assert "chown -R www-data" not in deploy
    assert "--require-hashes" in deploy
    env_sources = [
        line
        for line in deploy.splitlines()
        if "source" in line and ".env" in line and not line.lstrip().startswith("#")
    ]
    assert not env_sources, f"deploy.sh must not source .env for FLINTTRADE_DIR; found {env_sources}"


def _backend_src_relpaths() -> list[str]:
    """Return ``packages/.../src`` roots that hold a ``flinttrade_*`` package."""
    roots = {
        init.parent.parent.relative_to(_REPO_ROOT).as_posix()
        for init in _REPO_ROOT.glob("packages/*/*/src/flinttrade_*/__init__.py")
    }
    core = "packages/core/core/src"
    ordered = [core, *sorted(roots - {core})] if core in roots else sorted(roots)
    return ordered


def _execstart_text(unit: str) -> str:
    """Return ExecStart including backslash continuations, collapsed to one line."""
    blocks = _backslash_continued_commands(unit, "ExecStart=")
    assert blocks, "flinttrade.service must declare ExecStart"
    return " ".join(part.rstrip("\\").strip() for part in blocks[0].splitlines())


@pytest.mark.unit
def test_unit_execstart_matches_supported_backend_module() -> None:
    """Production must start the same backend module as ft.py and install-native.sh."""
    unit = _UNIT.read_text(encoding="utf-8")
    native = (_REPO_ROOT / "infra" / "install" / "install-native.sh").read_text(encoding="utf-8")
    runner = (_REPO_ROOT / "scripts" / "ft.py").read_text(encoding="utf-8")
    execstart = _execstart_text(unit)

    assert "-m flinttrade_core.app" in native
    assert '"-m", "flinttrade_core.app"' in runner or "-m flinttrade_core.app" in runner
    assert execstart.startswith("ExecStart=/opt/flinttrade/.venv/bin/python")
    assert "-m flinttrade_core.app" in execstart
    assert "gunicorn" not in execstart
    assert "eventlet" not in execstart


@pytest.mark.unit
def test_unit_pythonpath_covers_backend_packages() -> None:
    """A hashed lock venv does not install workspace packages; PYTHONPATH must."""
    unit = _UNIT.read_text(encoding="utf-8")
    env = _unit_environment(unit)
    pythonpath = env.get("PYTHONPATH", "")
    parts = pythonpath.split(":")
    expected = [f"{_PRODUCTION_PREFIX}/{rel}" for rel in _backend_src_relpaths()]
    missing = [path for path in expected if path not in parts]
    assert not missing, f"PYTHONPATH missing backend src roots: {missing}"


@pytest.mark.unit
def test_backend_packages_import_via_unit_pythonpath() -> None:
    """Prove unit PYTHONPATH, not an editable venv install, supplies workspace packages."""
    unit = _UNIT.read_text(encoding="utf-8")
    env = _unit_environment(unit)
    pythonpath = env.get("PYTHONPATH", "")
    remapped = pythonpath.replace(_PRODUCTION_PREFIX, _REPO_ROOT.as_posix())
    # Eager imports from flinttrade_core.app — not the heavy optional AI stack.
    script = """
from pathlib import Path
import flinttrade_core
import flinttrade_data
import flinttrade_gateway

def check(name, mod, needle):
    path = Path(mod.__file__).resolve().as_posix()
    if needle not in path:
        raise SystemExit(f"{name} loaded from {path}, expected {needle}")

check("flinttrade_core", flinttrade_core, "packages/core/core/src")
check("flinttrade_data", flinttrade_data, "packages/core/data/src")
check("flinttrade_gateway", flinttrade_gateway, "packages/integrations/gateway/src")
print("imports-ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": remapped},
        cwd=_REPO_ROOT,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "imports-ok" in result.stdout


_LINUX_DOC = _REPO_ROOT / "docs" / "setup" / "linux.md"
_PI_DOC = _REPO_ROOT / "docs" / "setup" / "raspberry-pi.md"
_SYSTEMD_README = _REPO_ROOT / "infra" / "systemd" / "README.md"


def _server_section(text: str) -> str:
    """Return the advanced server-services section of a setup page."""
    marker = "## Server services"
    if marker in text:
        return text[text.index(marker) :]
    marker = "## Setup (ARM64 server"
    if marker in text:
        return text[text.index(marker) :]
    return text


@pytest.mark.unit
def test_pi_docs_preserve_bookworm_and_supported_install_paths() -> None:
    """#155: Bookworm is 3.11; one-line/native stay the Pi path; production is Ubuntu 24.04."""
    pi = _PI_DOC.read_text(encoding="utf-8")
    assert "Bookworm" in pi
    assert "Python 3.11" in pi
    assert "web-install.sh" in pi
    assert "install-native.sh" in pi or "native installer" in pi.lower()
    assert "Ubuntu 24.04" in pi
    assert "setup-production" in pi
    assert ">=3.12" in pi or "3.12" in pi
    assert "FLINTTRADE_DIR" not in pi
    assert "gunicorn" not in pi.lower()
    assert "chowns the tree" not in pi


@pytest.mark.unit
def test_production_docs_do_not_duplicate_clone_or_chown_code_tree() -> None:
    """The installer clones /opt/flinttrade; docs must not pre-clone or chown the tree."""
    linux = _LINUX_DOC.read_text(encoding="utf-8")
    readme = _SYSTEMD_README.read_text(encoding="utf-8")
    server = _server_section(linux)
    assert "git clone" not in server
    assert "FLINTTRADE_DIR:-" not in server
    assert "${FLINTTRADE_DIR" not in server
    assert "gunicorn" not in server.lower()
    assert "eventlet" not in server.lower()
    assert "chowns the tree" not in server
    assert "sudoedit" in server or "sudo -e" in server
    install = readme.split("## Install", 1)[-1].split("## Usage", 1)[0]
    assert "git clone" not in install
    assert "FLINTTRADE_DIR:-" not in readme
    assert "${FLINTTRADE_DIR" not in readme
    assert "gunicorn" not in readme.lower()
    assert "sudoedit" in readme or "sudo -e" in readme


@pytest.mark.unit
def test_installer_makes_env_readable_only_to_root_and_service_group() -> None:
    """python-dotenv runs as www-data, so root:root 0600 makes first boot fail."""
    installer = _INSTALLER.read_text(encoding="utf-8")

    assert 'sudo chown "root:$SERVICE_USER" "$INSTALL_DIR/.env"' in installer
    assert 'sudo chmod 640 "$INSTALL_DIR/.env"' in installer
    assert 'sudo chmod 600 "$INSTALL_DIR/.env"' not in installer


@pytest.mark.unit
def test_deploy_always_refreshes_systemd_unit_before_restart() -> None:
    """Existing hosts must not retain the pre-fix gunicorn/workspace unit."""
    deploy = _DEPLOY.read_text(encoding="utf-8")

    assert 'if [ ! -f "/etc/systemd/system/${SERVICE_NAME}.service" ]' not in deploy
    assert 'sudo cp "infra/systemd/${SERVICE_NAME}.service" /etc/systemd/system/' in deploy
    assert 'sudo systemctl daemon-reload' in deploy


@pytest.mark.unit
def test_installer_validates_and_uses_the_same_system_python() -> None:
    """The version check must cover the interpreter that actually creates .venv."""
    installer = _INSTALLER.read_text(encoding="utf-8")

    assert 'PYTHON_BIN="/usr/bin/python3"' in installer
    assert 'flinttrade_assert_python_floor "$PYTHON_BIN"' in installer
    assert 'sudo "$PYTHON_BIN" -m venv "$VENV_DIR"' in installer


@pytest.mark.unit
def test_optional_tooling_uses_the_resolved_executable_under_sudo() -> None:
    """A user-local uv/pnpm discovery must not become a missing sudo PATH command."""
    installer = _INSTALLER.read_text(encoding="utf-8")

    assert 'UV_BIN="$(command -v uv)"' in installer
    assert 'sudo "$UV_BIN" sync' in installer
    assert 'PNPM_BIN="$(command -v pnpm)"' in installer
    assert 'sudo "$PNPM_BIN" install' in installer


@pytest.mark.unit
def test_root_owned_checkout_is_readable_but_not_writable_by_service_group() -> None:
    """A restrictive caller umask must not make root-owned code unreadable to www-data."""
    installer = _INSTALLER.read_text(encoding="utf-8")

    assert 'sudo chown -R "root:$SERVICE_USER" "$INSTALL_DIR"' in installer
    assert 'sudo chgrp -R "$SERVICE_USER" "$INSTALL_DIR"' in installer
    assert 'sudo chmod -R g+rX,go-w "$INSTALL_DIR"' in installer
    assert 'sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"' not in installer
