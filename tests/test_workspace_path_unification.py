"""Path-unification invariant: one module owns ``~/.flinttrade``, nobody else.

The Windows/macOS data-loss class had a single root cause: modules all over
``packages/`` hardcoded ``Path.home() / ".flinttrade"`` instead of asking the
workspace resolver. On Linux that literal happens to be right, so it never
failed in CI; on macOS the real workspace is
``~/Library/Application Support/flinttrade`` and on Windows it is
``%APPDATA%\\flinttrade``, so every hardcoded module wrote to a second, invisible
directory that the uninstaller then could not find and purge.

This file pins both halves of the fix:

  1. ``flinttrade_core.workspace`` is the only module allowed to spell the
     literal (it needs it for the legacy-migration probes).
  2. Both uninstallers enumerate the managed data roots — ``source-build``,
     ``data``, ``archive`` and ``sandbox`` — as purge targets. Grepping
     ``tests/test_desktop_uninstall_scripts.py`` for ``source-build`` returned
     nothing before this file existed, and that absence is exactly why the purge
     gap shipped.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

_UNINSTALL_SH = _REPO_ROOT / "scripts" / "install" / "flinttrade-uninstall.sh"
_UNINSTALL_PS1 = _REPO_ROOT / "scripts" / "install" / "flinttrade-uninstall.ps1"

# Matches Path.home() / ".flinttrade" and Path.home() / '.flinttrade/sub/path' in either
# quote style, tolerating arbitrary whitespace or line breaks around the division operator.
# The trailing group requires a separator, so an unrelated sibling such as
# ".flinttrade-backups" is not swept up.
_HARDCODED_WORKSPACE_RE = re.compile(
    r"""Path\s*\.\s*home\s*\(\s*\)\s*/\s*(['"])\.flinttrade(?:[/\\][^'"]*)?\1"""
)

# ---------------------------------------------------------------------------
# Allowlist. Every entry is a repo-relative POSIX path with a written reason.
# ---------------------------------------------------------------------------
_ALLOWED: dict[str, str] = {
    # THE canonical resolver. It must name the literal directly: it is the module that
    # decides `~/.flinttrade` on Linux, and it probes the same literal on macOS/Windows
    # to migrate data left behind by older builds that wrote there unconditionally.
    "packages/core/core/src/flinttrade_core/workspace.py": (
        "the single canonical resolver; needs the literal for the Linux branch and the "
        "legacy-migration probes on macOS/Windows"
    ),
    # The unit test that pins workspace.py's own per-OS branches. It asserts the literal
    # is what the resolver returns on Linux, so it must be free to spell it.
    "packages/core/core/tests/test_workspace.py": (
        "unit test for workspace.py itself; asserts the Linux branch resolves to the literal"
    ),
}

# Data roots the uninstallers must enumerate. `data`, `archive` and `sandbox` live under
# the literal `~/.flinttrade` dotdir on every OS (not under the per-OS workspace dir), and
# `source-build` is the build checkout at ~/.flinttrade/source-build/FlintTrade — all four
# survived --purge/-Purge before this guard existed.
_REQUIRED_DATA_TARGETS = ("source-build", "data", "archive", "sandbox")


def _data_target_re(token: str) -> re.Pattern[str]:
    """Build a regex matching ``token`` used as a real path component.

    Prose must not satisfy the guard, so the token has to be rooted in a variable-based
    path (``"$MANAGED_ROOT/data"``, ``"$ManagedRoot\\data"``) or supplied as a standalone
    quoted segment (``Join-Path $ManagedRoot "data"``). A sentence such as
    ``say "any ~/.flinttrade data/archive/sandbox storage"`` matches neither.

    Args:
        token: The path component the uninstaller must enumerate.

    Returns:
        A compiled pattern for that component.
    """
    escaped = re.escape(token)
    return re.compile(
        rf"""\$\{{?[A-Za-z_][A-Za-z0-9_]*\}}?[/\\]{escaped}\b"""  # "$MANAGED_ROOT/data"
        rf"""|(['"]){escaped}\1"""  # Join-Path $ManagedRoot "data"
    )


def _strip_hash_comments(text: str) -> str:
    """Blank out ``#`` comment tails; both uninstallers comment the same way.

    Args:
        text: Full script source.

    Returns:
        The source with comment text removed and line count preserved.
    """
    out: list[str] = []
    for line in text.splitlines():
        single = double = False
        cut = len(line)
        for index, char in enumerate(line):
            if char == "'" and not double:
                single = not single
            elif char == '"' and not single:
                double = not double
            elif char == "#" and not single and not double and (index == 0 or line[index - 1].isspace()):
                cut = index
                break
        out.append(line[:cut])
    return "\n".join(out)


@lru_cache(maxsize=1)
def _tracked_python_modules() -> tuple[Path, ...]:
    """Return every tracked ``.py`` file under ``packages/``.

    Returns:
        Absolute paths of tracked Python modules, empty when git is unusable.
    """
    git = shutil.which("git")
    if git is None:
        return ()
    result = subprocess.run(
        [git, "ls-files", "-z", "--", "packages"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    return tuple(
        _REPO_ROOT / rel
        for rel in result.stdout.split("\0")
        if rel.endswith(".py") and (_REPO_ROOT / rel).is_file()
    )


@pytest.mark.unit
def test_only_workspace_module_hardcodes_the_flinttrade_dotdir() -> None:
    """No package module may resolve the workspace itself — ask flinttrade_core.workspace."""
    modules = _tracked_python_modules()
    if not modules:
        pytest.skip("git ls-files returned nothing (git unavailable or not a work tree)")

    violations: list[str] = []
    for path in modules:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _HARDCODED_WORKSPACE_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line}: {match.group(0)}")

    assert not violations, (
        "Modules under packages/ must not hardcode Path.home() / '.flinttrade'. The workspace "
        "is per-OS (Linux ~/.flinttrade, macOS ~/Library/Application Support/flinttrade, "
        "Windows %APPDATA%\\flinttrade, overridden by FLINTTRADE_WORKSPACE_DIR then "
        "FLINTTRADE_HOME) — resolve it through flinttrade_core.workspace instead:\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_workspace_allowlist_has_not_gone_stale() -> None:
    """Every allowlisted file must exist and still contain the literal it is excused for."""
    stale: list[str] = []
    for rel, reason in _ALLOWED.items():
        path = _REPO_ROOT / rel
        if not path.is_file():
            stale.append(f"{rel}: allowlisted but missing ({reason})")
            continue
        if not _HARDCODED_WORKSPACE_RE.search(path.read_text(encoding="utf-8")):
            stale.append(f"{rel}: allowlisted but no longer contains the literal — drop the entry")

    assert not stale, "Stale entries in _ALLOWED:\n" + "\n".join(stale)


@pytest.mark.unit
@pytest.mark.parametrize("script", [_UNINSTALL_SH, _UNINSTALL_PS1], ids=["uninstall.sh", "uninstall.ps1"])
def test_uninstallers_enumerate_every_managed_data_root(script: Path) -> None:
    """--purge / -Purge must reach source-build, data, archive and sandbox."""
    assert script.is_file(), f"{script} is missing (installers must not be moved or renamed)"
    text = _strip_hash_comments(script.read_text(encoding="utf-8"))

    missing = [token for token in _REQUIRED_DATA_TARGETS if not _data_target_re(token).search(text)]

    assert not missing, (
        f"{script.name} does not list {', '.join(missing)} as data target(s). Purge must cover the "
        "managed roots under the literal ~/.flinttrade dotdir (source-build, data, archive, "
        "sandbox) on every OS, not just the per-OS workspace directory."
    )
