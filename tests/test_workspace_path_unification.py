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
  2. Both uninstallers enumerate every managed data root — ``src``, ``tools``,
     ``source-build``, ``data``, ``archive`` and ``sandbox`` — as purge targets.
     Grepping ``tests/test_desktop_uninstall_scripts.py`` for ``source-build``
     returned nothing before this file existed, and that absence is exactly why
     the purge gap shipped.

     That second guard used to assert only that each token appeared *somewhere*
     in the script as a path component, which a variable definition alone
     satisfies: deleting the matching ``add_data_target`` /
     ``$candidates`` entries left the definitions in place and the guard still
     passed while ``--purge`` silently skipped the directory. It now parses the
     body of the collection function itself (``collect_data_targets`` /
     ``Get-DataTargets``) and requires each root to be *referenced there*.
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

# ---------------------------------------------------------------------------
# Known debt, frozen. These modules still hardcode the literal and are NOT fixed
# by the install PR that introduced this guard.
#
# They are excluded deliberately, not accidentally. Re-pointing them at the
# resolver changes where live trading state is read from — `credentials.py` is
# the encrypted broker-credential vault, `trade_journal.py` holds realised P&L,
# and the `flinttrade_engine` modules back the safety and strategy paths. Each
# needs its own migration story and its own tests; bundling that into an
# installer fix would have hidden a data-migration change inside a docs PR.
#
# This list may only ever SHRINK. `test_known_workspace_debt_only_shrinks`
# fails if an entry stops containing the literal (fix it, then delete the line),
# and the main guard fails if any file NOT listed here introduces it. The class
# therefore cannot grow while the backlog is worked off.
# ---------------------------------------------------------------------------
_KNOWN_DEBT: frozenset[str] = frozenset(
    {
        "packages/core/core/src/flinttrade_core/health_monitor.py",
        "packages/core/core/src/flinttrade_core/monitoring.py",
        "packages/core/core/src/flinttrade_core/preset_routes.py",
        "packages/core/core/src/flinttrade_core/shortcuts_routes.py",
        "packages/core/core/src/flinttrade_core/totp_auth.py",
        "packages/core/core/src/flinttrade_core/traffic_logger.py",
        "packages/core/historical/src/flinttrade_historical/expiry_tracker.py",
        "packages/core/historical/src/flinttrade_historical/watchlist.py",
        "packages/core/historical/src/flinttrade_historical/watchlist_routes.py",
        "packages/integrations/gateway/src/flinttrade_gateway/credentials.py",
        "packages/integrations/webhooks/src/flinttrade_webhooks/flow_store.py",
        "packages/services/ai/src/flinttrade_ai/pipeline.py",
        "packages/services/engine/src/flinttrade_engine/action_center.py",
        "packages/services/engine/src/flinttrade_engine/latency_monitor.py",
        "packages/services/engine/src/flinttrade_engine/qty_freeze.py",
        "packages/services/engine/src/flinttrade_engine/strategy.py",
        "packages/services/engine/src/flinttrade_engine/strategy_hot_reload.py",
        "packages/services/journal/src/flinttrade_journal/trade_journal.py",
        "packages/services/screener/src/flinttrade_screener/fii_dii.py",
    }
)

# Data roots the uninstallers must enumerate, all directly under the literal
# `~/.flinttrade` managed root on every OS (not under the per-OS workspace dir):
#
#   src           managed source checkout   ~/.flinttrade/src/FlintTrade
#   tools         managed toolchain         ~/.flinttrade/tools
#   source-build  build checkout            ~/.flinttrade/source-build/FlintTrade
#   data          pre-workspace DuckDB store, incl. the ditto credential vault
#   archive       append-only audit chain
#   sandbox       Practice-mode state
#
# All six survived --purge/-Purge before this guard existed.
_REQUIRED_DATA_TARGETS = ("src", "tools", "source-build", "data", "archive", "sandbox")

# The function in each uninstaller that builds the purge-candidate list. Naming a
# variable is not enough — it has to be collected *here*.
_COLLECTOR_HEADERS = {
    ".sh": re.compile(r"^collect_data_targets\s*\(\s*\)\s*\{", re.M),
    ".ps1": re.compile(r"^function\s+Get-DataTargets\s*\{", re.M),
}

# `NAME=<value>` (shell) and `$Name = <value>` (PowerShell) assignments.
_SH_ASSIGNMENT_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=(.+)$", re.M)
_PS_ASSIGNMENT_RE = re.compile(r"^\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", re.M)

# Any `$VAR` / `${VAR}` / `$Var` reference.
_VARIABLE_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")

# Lines that only print to the operator. A root named in a warning is not a root the
# script deletes, so these must not satisfy the guard.
_MESSAGE_LINE_RE = re.compile(r"^\s*(?:say|warn|fail|printf|echo|Say|Write-[A-Za-z]+)\b")


def _final_path_component(value: str) -> str:
    """Return the last path component a variable's right-hand side resolves to.

    Handles both dialects by reducing the expression to its final token and then to
    that token's final path segment::

        "$MANAGED_ROOT/data"            -> data
        Join-Path $ManagedRoot "src"    -> src
        "$LEGACY_DATA_DIR/ditto.db"     -> ditto.db

    Args:
        value: The right-hand side of an assignment, comments already stripped.

    Returns:
        The final path component, or an empty string when there is nothing to read.
    """
    tokens = value.replace('"', " ").replace("'", " ").split()
    if not tokens:
        return ""
    return re.split(r"[/\\]", tokens[-1])[-1]


def _collector_body(text: str, suffix: str) -> str:
    """Slice out the body of the purge-candidate collection function.

    Located by its header and closed on the first column-zero ``}``, so the guard
    survives edits inside the function and never depends on line numbers.

    Args:
        text: Full script source with comments already stripped.
        suffix: ``".sh"`` or ``".ps1"``, selecting the header pattern.

    Returns:
        The function body, or an empty string when the function is not found.
    """
    header = _COLLECTOR_HEADERS[suffix].search(text)
    if header is None:
        return ""
    rest = text[header.end() :]
    close = re.search(r"^\}", rest, re.M)
    return rest[: close.start()] if close else rest


def _collected_components(text: str, body: str, suffix: str) -> set[str]:
    """Every path component the collection function actually adds as a candidate.

    Combines two sources: variables *referenced in the body* resolved through their
    definition elsewhere in the script, and inline path literals written in the body
    itself. Operator-message lines are excluded — naming a directory in a warning is
    not enumerating it.

    Args:
        text: Full script source with comments already stripped.
        body: The collection function's body.
        suffix: ``".sh"`` or ``".ps1"``, selecting the assignment pattern.

    Returns:
        The set of final path components the function collects.
    """
    assignment_re = _SH_ASSIGNMENT_RE if suffix == ".sh" else _PS_ASSIGNMENT_RE
    defined: dict[str, set[str]] = {}
    for name, value in assignment_re.findall(text):
        component = _final_path_component(value)
        if component:
            defined.setdefault(name, set()).add(component)

    collected: set[str] = set()
    for line in body.splitlines():
        if _MESSAGE_LINE_RE.match(line):
            continue
        for name in _VARIABLE_REF_RE.findall(line):
            collected |= defined.get(name, set())
        # An inline literal such as `add_data_target "$MANAGED_ROOT/data"` or
        # `(Join-Path $ManagedRoot "data")` counts on its own.
        for literal in re.findall(r"""(['"])([^'"]+)\1""", line):
            collected.add(re.split(r"[/\\]", literal[1])[-1])
    return collected


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
        if rel in _ALLOWED or rel in _KNOWN_DEBT:
            continue
        text = path.read_text(encoding="utf-8")
        for match in _HARDCODED_WORKSPACE_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{rel}:{line}: {match.group(0)}")

    assert not violations, (
        "Modules under packages/ must not hardcode Path.home() / '.flinttrade'. The workspace "
        "is per-OS (Linux ~/.flinttrade, macOS ~/Library/Application Support/flinttrade, "
        "Windows %APPDATA%\\flinttrade, overridden by FLINTTRADE_WORKSPACE_DIR then "
        "FLINTTRADE_HOME) — resolve it through flinttrade_core.workspace instead.\n"
        "Do NOT silence this by adding the file to _KNOWN_DEBT: that set is frozen and may "
        "only shrink.\n" + "\n".join(violations)
    )


@pytest.mark.unit
def test_known_workspace_debt_only_shrinks() -> None:
    """A fixed module must be deleted from ``_KNOWN_DEBT``, never left to rot there.

    The debt set is a ratchet. Once a module stops hardcoding the literal, its entry is
    stale and would silently re-permit a regression in that same file, so this fails until
    the line is removed.
    """
    modules = _tracked_python_modules()
    if not modules:
        pytest.skip("git ls-files returned nothing (git unavailable or not a work tree)")

    by_rel = {path.relative_to(_REPO_ROOT).as_posix(): path for path in modules}

    missing = sorted(rel for rel in _KNOWN_DEBT if rel not in by_rel)
    assert not missing, (
        "These _KNOWN_DEBT entries no longer exist as tracked modules — delete them:\n"
        + "\n".join(missing)
    )

    already_fixed = sorted(
        rel
        for rel in _KNOWN_DEBT
        if not _HARDCODED_WORKSPACE_RE.search(by_rel[rel].read_text(encoding="utf-8"))
    )
    assert not already_fixed, (
        "These modules no longer hardcode Path.home() / '.flinttrade'. Remove them from "
        "_KNOWN_DEBT so the guard starts protecting them:\n" + "\n".join(already_fixed)
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
    """--purge / -Purge must reach every managed root, as a *collected candidate*.

    Deliberately not a whole-file token search: the variable definitions
    (``LEGACY_DATA_DIR="$MANAGED_ROOT/data"`` and friends) sit at the top of both
    scripts and satisfy such a search on their own, so deleting the corresponding
    ``add_data_target`` / ``$candidates`` entries used to leave the guard green while
    ``--purge`` walked past the directory. This parses the collection function's body
    and requires each root to be reachable from *there*.
    """
    assert script.is_file(), f"{script} is missing (installers must not be moved or renamed)"
    suffix = script.suffix
    text = _strip_hash_comments(script.read_text(encoding="utf-8"))

    body = _collector_body(text, suffix)
    assert body.strip(), (
        f"{script.name}: could not find the purge-candidate collection function "
        f"({_COLLECTOR_HEADERS[suffix].pattern!r}). If it was renamed, update "
        "_COLLECTOR_HEADERS — do not delete this guard."
    )

    collected = _collected_components(text, body, suffix)
    missing = [token for token in _REQUIRED_DATA_TARGETS if token not in collected]

    assert not missing, (
        f"{script.name}: the purge-candidate collection function never adds "
        f"{', '.join(missing)}. Purge must cover every managed root under the literal "
        "~/.flinttrade dotdir (src, tools, source-build, data, archive, sandbox) on every "
        "OS, not just the per-OS workspace directory. Defining the variable is not enough — "
        "it has to be added as a candidate inside the function."
    )
