"""Contract tests for ``scripts/reset-flinttrade-state.sh``.

The script archives and then deletes the whole workspace directory, so the only
thing standing between it and the wrong tree is how it resolves the workspace
override. ``flinttrade_core.workspace`` resolves both overrides with
``Path(value).expanduser().resolve()``; an override written literally as
``~/custom-workspace`` — the spelling every env file and service unit uses,
since neither expands ``~`` — must therefore reach the same directory here.
Before this was fixed the quoted tilde was taken as a directory named ``~``
below the repository root, so the reset wiped that, reported success, and left
the real workspace untouched.

Every test runs against a throwaway copy of the script inside ``tmp_path`` so
the archive it writes lands there rather than in the developer's checkout, and
``lsof``/``netstat`` are stubbed so no real backend process is ever signalled.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reset-flinttrade-state.sh"

BASH = shutil.which("bash")
NO_BASH_REASON = "bash is not available on this runner"
NOT_POSIX_REASON = "the reset script resolves POSIX paths; Windows path translation breaks the fixture"


def _sandbox(tmp_path: Path) -> Path:
    """Copy the reset script into a throwaway repository root.

    Args:
        tmp_path: Per-test temporary directory.

    Returns:
        The sandbox repository root holding ``scripts/reset-flinttrade-state.sh``.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCRIPT, repo / "scripts" / SCRIPT.name)
    return repo


def _fake_bin(tmp_path: Path) -> str:
    """Return a PATH that reports Linux and finds no listening backend."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uname = bin_dir / "uname"
    uname.write_text("#!/bin/sh\nprintf '%s\\n' Linux\n", encoding="utf-8", newline="\n")
    uname.chmod(0o755)
    for tool in ("lsof", "netstat", "taskkill"):
        stub = bin_dir / tool
        stub.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    return f"{bin_dir}{os.pathsep}/usr/bin:/bin"


def _run(tmp_path: Path, repo: Path, home: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    """Run the sandboxed reset script with the given workspace overrides."""
    env = {"PATH": _fake_bin(tmp_path), "HOME": str(home)}
    env.update(overrides)
    return subprocess.run(
        [BASH, str(repo / "scripts" / SCRIPT.name)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )


def _workspace_with_state(home: Path, name: str = "custom-workspace") -> Path:
    """Create a workspace directory holding a file the reset must archive and wipe."""
    workspace = home / name
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "credentials.db").write_text("encrypted-broker-credentials", encoding="utf-8")
    return workspace


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.parametrize("variable", ["FLINTTRADE_WORKSPACE_DIR", "FLINTTRADE_HOME"])
def test_reset_expands_a_literal_tilde_workspace_override(tmp_path: Path, variable: str) -> None:
    """A quoted '~/…' override must reach the real workspace, not a directory named '~'."""
    repo = _sandbox(tmp_path)
    home = tmp_path / "home"
    workspace = _workspace_with_state(home)

    result = _run(tmp_path, repo, home, **{variable: "~/custom-workspace"})

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (workspace / "credentials.db").exists(), (
        f"{variable}='~/custom-workspace' left the real workspace untouched"
    )
    assert workspace.is_dir(), "the reset must leave an empty workspace behind for the backend"
    assert not (repo / "~").exists() and not (home / "~").exists(), (
        "the literal tilde was treated as a directory name, so the wrong tree was wiped"
    )
    assert str(workspace) in result.stdout, "the reported path must be the expanded workspace"
    archived = list((repo / ".local" / "archive").glob("flinttrade-state-*/credentials.db"))
    assert archived, "the workspace was wiped without archiving its contents first"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
def test_reset_makes_a_relative_workspace_override_absolute(tmp_path: Path) -> None:
    """A relative override is resolved once, so the reported path is the deleted path."""
    repo = _sandbox(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    workspace = repo / "relative-workspace"
    workspace.mkdir()
    (workspace / "credentials.db").write_text("x", encoding="utf-8")

    result = _run(tmp_path, repo, home, FLINTTRADE_WORKSPACE_DIR="relative-workspace")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (workspace / "credentials.db").exists()
    assert str(workspace) in result.stdout, "a relative override must be reported as an absolute path"


@pytest.mark.unit
@pytest.mark.skipif(BASH is None, reason=NO_BASH_REASON)
@pytest.mark.skipif(os.name != "posix", reason=NOT_POSIX_REASON)
@pytest.mark.parametrize("override", ["~", "$HOME"])
def test_reset_refuses_to_wipe_the_whole_home_directory(tmp_path: Path, override: str) -> None:
    """'rm -rf' on an expanded override must never be aimed at the home directory itself."""
    repo = _sandbox(tmp_path)
    home = tmp_path / "home"
    keepsake = home / "unrelated.txt"
    home.mkdir(parents=True, exist_ok=True)
    keepsake.write_text("not FlintTrade state", encoding="utf-8")

    value = str(home) if override == "$HOME" else override
    result = _run(tmp_path, repo, home, FLINTTRADE_WORKSPACE_DIR=value)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "not a FlintTrade workspace directory" in result.stderr
    assert keepsake.exists(), "the reset deleted the home directory it was pointed at"
