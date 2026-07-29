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
     literal (it needs it for the legacy-migration probes, which is what
     ``legacy_dotdir()`` exists for). Every other module resolves through it, in
     a function body at call time, and copies its pre-workspace artefact forward
     once. The guard matches all five spellings of the literal, not just the
     division form: a docstring example is how the literal kept propagating into
     new modules, so unqualified examples count as violations too. Each of the
     three ratchet sets excuses a file for the spellings it is actually in debt
     for and no others, so a listed file stays fully guarded against the rest.
  2. Both uninstallers enumerate every managed data root — ``src``, ``tools``,
     ``source-build``, ``data``, ``archive``, ``sandbox``, plus the user-authored
     ``flows``, ``models`` and ``strategies`` trees — as purge targets.
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

# Every spelling of "the workspace is ~/.flinttrade" that a module can reach for.
#
# The original guard matched only the division form, which let equivalent evasions
# through — and the class it exists to stop does not care which one a module picks,
# because they all resolve to the same wrong directory on macOS and Windows. The
# forms are, in order:
#
#   1. Path.home() / ".flinttrade"          (and '.flinttrade/sub/path', either quote style)
#   2. Path.home().joinpath(".flinttrade", …)
#   3. "~/.flinttrade…"                     (Path("~/…"), expanduser("~/…"), os.path.join)
#   4. f"{Path.home()}/.flinttrade…"
#   5. ``~/.flinttrade…``                   (a reStructuredText/Markdown inline literal in a
#                                            docstring or comment — a misleading example is how
#                                            the literal keeps getting copied into new modules)
#
# Every form ends at a separator or at its own closing delimiter, so an unrelated
# sibling such as ".flinttrade-backups" is not swept up by ANY of them — forms 2-4
# used to stop at the bare literal and did match such siblings. Form 4 additionally
# requires the home call *inside* the interpolation, so home-anchor-free archive
# names such as test_backup.py's f".flinttrade/{name}" arcnames stay unmatched.
#
# Named groups, not numbered backreferences: the forms are recombined into more
# than one compiled pattern below, and numbered backreferences would silently
# rebind when the alternation order changed.
_DIVISION_FORM = r"""Path\s*\.\s*home\s*\(\s*\)\s*/\s*(?P<q1>['"])\.flinttrade(?:[/\\][^'"]*)?(?P=q1)"""
_JOINPATH_FORM = r"""home\s*\(\s*\)\s*\.\s*joinpath\s*\(\s*(?P<q2>['"])\.flinttrade(?:[/\\][^'"]*)?(?P=q2)"""
_QUOTED_TILDE_FORM = r"""(?P<q3>['"])~[/\\]\.flinttrade(?:[/\\][^'"\n]*)?(?P=q3)"""
_FSTRING_HOME_FORM = (
    r"""f(?P<q4>['"])[^'"\n]*\{[^}]*home\(\)[^}]*\}[/\\]\.flinttrade(?:[/\\][^'"\n]*)?(?P=q4)"""
)
# Backticks cannot delimit a Python string, so form 5 only ever occurs in prose.
# One backtick is enough to anchor on: the reStructuredText double-backtick style
# this repo writes matches on its inner pair.
_DOC_LITERAL_TILDE_FORM = r"""(?P<q5>`)~[/\\]\.flinttrade(?:[/\\][^'"`\n]*)?(?P=q5)"""

# The original alternation — the one the nineteen-module wave was reviewed against.
_DIVISION_FORM_RE = re.compile(_DIVISION_FORM)

# The spellings that only came into scope when the guard was widened.
_STRING_LITERAL_FORMS_RE = re.compile("|".join((_JOINPATH_FORM, _QUOTED_TILDE_FORM, _FSTRING_HOME_FORM)))

# Prose form, checked separately because it needs the qualification rule below.
_DOC_MENTION_RE = re.compile(_DOC_LITERAL_TILDE_FORM)

# Every executable spelling: what _ALLOWED and _KNOWN_DEBT are judged against.
_HARDCODED_WORKSPACE_RE = re.compile(
    "|".join((_DIVISION_FORM, _JOINPATH_FORM, _QUOTED_TILDE_FORM, _FSTRING_HOME_FORM))
)

# ---------------------------------------------------------------------------
# When a prose mention of the literal is NOT a violation.
#
# Form 5 fires on every docstring that says the word, and most of those docstrings
# are the fix rather than the bug: the migration waves deliberately document where
# each artefact used to live and where it lives now. Two shapes are correct and are
# therefore excused, and nothing else is:
#
#   per-OS qualified   the same paragraph also names the macOS or Windows root, so
#                      the reader is told ~/.flinttrade is only the Linux answer
#                      ("``~/.flinttrade`` on Linux, ``~/Library/Application
#                      Support/flinttrade`` on macOS, ``%APPDATA%/flinttrade`` on
#                      Windows").
#   legacy-marked      the paragraph marks the path as the pre-workspace root the
#                      module migrates *from* ("a pre-workspace
#                      ``~/.flinttrade/flows`` tree is copied into the workspace
#                      once"), which is exactly what legacy_dotdir() is for.
#
# A bare "state lives in ``~/.flinttrade/x``" is neither, and is the misleading
# example the guard exists to stop. Satisfying this rule is not an escape hatch —
# naming the other two platforms, or saying "legacy", IS the fix.
_DOC_MENTION_QUALIFIER_RE = re.compile(
    r"Application Support|APPDATA|macOS|Windows|legacy|pre-workspace", re.IGNORECASE
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
    # The workspace.json schema owner. Its `storage.fast` / `storage.archive` defaults
    # are not a resolver: they are the exact sentinel strings workspace.py compares
    # against in `_uses_implicit_default_storage` to decide whether an operator ever
    # chose a storage path. Changing them here would silently disable that check and
    # with it every `data/`-level legacy migration.
    "packages/core/core/src/flinttrade_core/workspace_migrations.py": (
        "owns the workspace.json schema defaults, which are the migration sentinels "
        "workspace.py matches on; the literal is data, not a resolution"
    ),
}

# ---------------------------------------------------------------------------
# Known debt, frozen — now EMPTY.
#
# This set held the nineteen modules that hardcoded the division form of the
# literal and were excluded from the install PR that introduced this guard,
# because re-pointing them at the resolver changes where live trading state is
# read from: `credentials.py` is the encrypted broker-credential vault,
# `trade_journal.py` holds realised P&L, and the `flinttrade_engine` modules back
# the safety and strategy paths. Each needed its own migration story and its own
# tests. All nineteen were worked off by the path-unification waves; every one
# now resolves through `flinttrade_core.workspace` and copies its pre-workspace
# artefact forward once, so every line has been deleted.
#
# Both the set and `_DEBT_CAP` are retained at zero deliberately. Re-admitting a
# module is then a two-line, review-visible edit rather than a silent append.
#
# This set may only ever SHRINK. `test_workspace_debt_only_shrinks` fails if an
# entry stops containing the literal (fix it, then delete the line), and the main
# guard fails if any file NOT listed here introduces it.
# ---------------------------------------------------------------------------
_KNOWN_DEBT: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# String-literal debt — a SEPARATE, newly exposed class, not part of the
# nineteen above.
#
# Widening the guard from the division form alone to every spelling brought these
# files into scope for the first time. They are the same per-OS bug — a module that
# writes to `~/.flinttrade/x` on Windows writes to a second, invisible directory the
# uninstaller cannot find — but they were outside the nineteen-module scope the
# waves were designed and reviewed against, so re-pointing them (and migrating
# `screener_cache.duckdb`, `memory/` and `expiry_data/`) belongs to its own change
# with its own migration tests.
#
# Kept apart from `_KNOWN_DEBT` on purpose: that set's story is finished, and
# folding a new backlog into it would erase the fact that it reached zero.
#
# These entries are NOT a blanket excuse for the file. Each is in debt for the
# non-division spellings only and is still checked against `_DIVISION_FORM_RE`, so
# adding `Path.home() / ".flinttrade"` to any of them fails the guard exactly as it
# would in a file that was never listed. Excusing them outright — which is what
# folding them into `_EXCUSED` did — regressed coverage they already had.
#
#   app.py                  operator-facing log message only; names the wrong
#                           backup path on macOS/Windows. One-line reword.
#   expiry_collector.py     live default argument (`data_dir`).
#   memory.py               live `_DEFAULT_PERSIST_DIR` + a docstring example.
#   position_tracker.py     docstring examples only; the real default is ":memory:".
#   state_manager.py        docstring example only; the real default is ":memory:".
#   stock_cache.py          live `_DEFAULT_DB_PATH`.
# ---------------------------------------------------------------------------
_STRING_LITERAL_DEBT: frozenset[str] = frozenset(
    {
        "packages/core/core/src/flinttrade_core/app.py",
        "packages/core/historical/src/flinttrade_historical/expiry_collector.py",
        "packages/services/ai/src/flinttrade_ai/memory.py",
        "packages/services/engine/src/flinttrade_engine/position_tracker.py",
        "packages/services/engine/src/flinttrade_engine/state_manager.py",
        "packages/services/screener/src/flinttrade_screener/stock_cache.py",
    }
)

# ---------------------------------------------------------------------------
# Prose debt — the files carrying an unqualified reStructuredText mention of the
# literal, exposed when form 5 was added.
#
# Alternation 3 used to demand a quote immediately before the tilde, so it saw
# `"~/.flinttrade/x"` in code and missed ``~/.flinttrade/x`` in a docstring — the
# style this repo actually writes. Adding form 5 surfaced twenty-six files; all but
# these are correct per-OS or legacy-marked documentation and are excused by
# `_DOC_MENTION_QUALIFIER_RE` rather than listed here.
#
# What remains is a prose fix in each case — name the macOS and Windows roots, or
# say "legacy" — but the files belong to other packages and other reviewers, so
# they are listed rather than silently rewritten. Deliberately a THIRD set:
# `_KNOWN_DEBT` and `_STRING_LITERAL_DEBT` keep their exact contents and caps.
#
# An entry here excuses form 5 ONLY. Forms 1-4 stay live in these files.
#
#   cache.py                 "suitable for ``~/.flinttrade/`` data directories".
#   desktop.py               module header + `_ensure_workspace` both present the
#                            dotdir as where workspace.json is created.
#   excel_routes.py          documents the EXCEL_OUTPUT_DIR default.
#   expiry_tracker.py        one trailing sentence, unlike its per-OS-qualified
#                            migration docstring above it.
#   test_contracts.py        \
#   test_credentials.py       > test-isolation prose ("no files are written to …").
#   engine/tests/conftest.py /
#   test_flow_routes.py      one test docstring.
#   test_totp_auth.py        one test docstring.
# ---------------------------------------------------------------------------
_DOC_MENTION_DEBT: frozenset[str] = frozenset(
    {
        "packages/core/core/src/flinttrade_core/cache.py",
        "packages/core/core/src/flinttrade_core/desktop.py",
        "packages/core/core/tests/test_totp_auth.py",
        "packages/core/historical/src/flinttrade_historical/expiry_tracker.py",
        "packages/integrations/gateway/tests/test_contracts.py",
        "packages/integrations/gateway/tests/test_credentials.py",
        "packages/integrations/webhooks/src/flinttrade_webhooks/excel_routes.py",
        "packages/integrations/webhooks/tests/test_flow_routes.py",
        "packages/services/engine/tests/conftest.py",
    }
)

# Shrink-only ratchets. Lower a cap in the same commit that empties a wave; never
# raise one. Raising a cap is the review-visible act that admits new debt.
_DEBT_CAP: int = 0
_STRING_LITERAL_DEBT_CAP: int = 6
_DOC_MENTION_DEBT_CAP: int = 9

# Every path the main guard skips ENTIRELY. The two form-scoped debt sets are
# deliberately absent: excusing a whole file for a spelling it is not in debt for
# is how coverage silently regresses.
_EXCUSED: frozenset[str] = frozenset(_ALLOWED) | _KNOWN_DEBT

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
#
# The last three are user-AUTHORED trees, not caches, and each is now the target
# of a copy-once migration, so a pre-workspace copy is left behind on every
# upgraded macOS/Windows install:
#
#   flows         FlowBuilder flow definitions
#   models        trained signal models (signal_model.joblib and its .sha256)
#   strategies    user strategy files and per-strategy state.json
#
# `add_data_target "$MANAGED_ROOT"` would delete all three transitively, but only
# by never naming them: the operator would confirm an irreversible purge of their
# own strategy code from a list that did not mention it. Pinning them here forces
# the collector to enumerate each one so the printed list is complete.
_REQUIRED_DATA_TARGETS = (
    "src",
    "tools",
    "source-build",
    "data",
    "archive",
    "sandbox",
    "flows",
    "models",
    "strategies",
)

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


def _enclosing_paragraph(lines: list[str], index: int) -> str:
    """Return the run of non-blank lines containing ``lines[index]``.

    A docstring paragraph is the unit the qualification rule reads, because the
    per-OS enumeration a correct mention belongs to routinely wraps over three or
    four lines and would be invisible to a single-line check.

    Args:
        lines: The file split into lines.
        index: Zero-based index of the line the match starts on.

    Returns:
        The paragraph, newline-joined.
    """
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return "\n".join(lines[start : end + 1])


def _unqualified_doc_mentions(text: str) -> list[tuple[int, str]]:
    """Return every prose mention of the literal that is neither per-OS nor legacy-marked.

    Args:
        text: Full module source.

    Returns:
        ``(line number, matched text)`` for each mention that fails the rule.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    for match in _DOC_MENTION_RE.finditer(text):
        index = text.count("\n", 0, match.start())
        if _DOC_MENTION_QUALIFIER_RE.search(_enclosing_paragraph(lines, index)):
            continue
        found.append((index + 1, match.group(0)))
    return found


def _violations_in(rel: str, text: str) -> list[str]:
    """Collect the guard violations in one module, honouring the form-scoped debt sets.

    A debt entry excuses the file for the forms it is in debt for and nothing else,
    so a listed file still fails on any spelling outside its own backlog.

    Args:
        rel: Repo-relative POSIX path, used to select the applicable forms.
        text: Full module source.

    Returns:
        Formatted ``path:line: match`` strings, empty when the module is clean.
    """
    code_forms = _DIVISION_FORM_RE if rel in _STRING_LITERAL_DEBT else _HARDCODED_WORKSPACE_RE
    violations: list[str] = []
    for match in code_forms.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        violations.append(f"{rel}:{line}: {match.group(0)}")
    if rel not in _STRING_LITERAL_DEBT and rel not in _DOC_MENTION_DEBT:
        violations += [f"{rel}:{line}: {matched}" for line, matched in _unqualified_doc_mentions(text)]
    return violations


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
        if rel in _EXCUSED:
            continue
        violations += _violations_in(rel, path.read_text(encoding="utf-8"))

    assert not violations, (
        "Modules under packages/ must not hardcode the ~/.flinttrade literal in ANY spelling "
        "(division, joinpath, a quoted '~/.flinttrade…' string, an f-string over Path.home(), or "
        "an unqualified ``~/.flinttrade…`` docstring literal). The workspace is per-OS (Linux "
        "~/.flinttrade, macOS ~/Library/Application Support/flinttrade, Windows "
        "%APPDATA%\\flinttrade, overridden by FLINTTRADE_WORKSPACE_DIR then FLINTTRADE_HOME) — "
        "resolve it through flinttrade_core.workspace instead, and reach for "
        "flinttrade_core.workspace.legacy_dotdir() when you need the pre-workspace root for a "
        "migration probe. In prose, name the macOS and Windows roots alongside it or say the "
        "mention is the legacy/pre-workspace one.\n"
        "Do NOT silence this by adding the file to _KNOWN_DEBT, _STRING_LITERAL_DEBT or "
        "_DOC_MENTION_DEBT: all three are capped and may only shrink.\n" + "\n".join(violations)
    )


def _still_in_debt_for(kind: str, text: str) -> bool:
    """Report whether a module still carries the spelling its debt set excuses.

    Args:
        kind: ``"code"`` for the executable spellings, ``"prose"`` for form 5.
        text: Full module source.

    Returns:
        True while the entry is still earning its place in the set.
    """
    if kind == "prose":
        return bool(_unqualified_doc_mentions(text))
    return bool(_HARDCODED_WORKSPACE_RE.search(text))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("debt", "kind", "name"),
    [
        (_KNOWN_DEBT, "code", "_KNOWN_DEBT"),
        (_STRING_LITERAL_DEBT, "code", "_STRING_LITERAL_DEBT"),
        (_DOC_MENTION_DEBT, "prose", "_DOC_MENTION_DEBT"),
    ],
    ids=["known-debt", "string-literal-debt", "doc-mention-debt"],
)
def test_workspace_debt_only_shrinks(debt: frozenset[str], kind: str, name: str) -> None:
    """A fixed module must be deleted from its debt set, never left to rot there.

    Each debt set is a ratchet. Once a module stops hardcoding the literal, its entry is
    stale and would silently re-permit a regression in that same file, so this fails until
    the line is removed.

    Args:
        debt: The debt set under test.
        kind: Which spellings the set excuses — ``"code"`` or ``"prose"``.
        name: Its identifier, for the failure message.
    """
    modules = _tracked_python_modules()
    if not modules:
        pytest.skip("git ls-files returned nothing (git unavailable or not a work tree)")

    by_rel = {path.relative_to(_REPO_ROOT).as_posix(): path for path in modules}

    missing = sorted(rel for rel in debt if rel not in by_rel)
    assert not missing, (
        f"These {name} entries no longer exist as tracked modules — delete them:\n" + "\n".join(missing)
    )

    already_fixed = sorted(
        rel for rel in debt if not _still_in_debt_for(kind, by_rel[rel].read_text(encoding="utf-8"))
    )
    assert not already_fixed, (
        "These modules no longer hardcode the ~/.flinttrade literal. Remove them from "
        f"{name} so the guard starts protecting them:\n" + "\n".join(already_fixed)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("debt", "cap", "name"),
    [
        (_KNOWN_DEBT, _DEBT_CAP, "_KNOWN_DEBT/_DEBT_CAP"),
        (_STRING_LITERAL_DEBT, _STRING_LITERAL_DEBT_CAP, "_STRING_LITERAL_DEBT/_STRING_LITERAL_DEBT_CAP"),
        (_DOC_MENTION_DEBT, _DOC_MENTION_DEBT_CAP, "_DOC_MENTION_DEBT/_DOC_MENTION_DEBT_CAP"),
    ],
    ids=["known-debt", "string-literal-debt", "doc-mention-debt"],
)
def test_workspace_debt_never_grows(debt: frozenset[str], cap: int, name: str) -> None:
    """Each debt set is a shrink-only ratchet; raising its cap is a review-visible act.

    ``test_workspace_debt_only_shrinks`` forces a fixed entry out of the set, but on its
    own it does not stop a *new* module being appended. The cap does: admitting debt
    requires editing a number as well as the list, in the same diff a reviewer reads.

    Args:
        debt: The debt set under test.
        cap: Its declared upper bound.
        name: Identifiers for the failure message.
    """
    assert len(debt) <= cap, (
        f"{name}: the set has grown to {len(debt)} entries against a cap of {cap}. Fix the "
        "module instead. If new debt genuinely has to be admitted, raise the cap in the same "
        "commit and say why in the review."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "spelling",
    [
        'Path.home() / ".flinttrade"',
        "Path.home() / '.flinttrade' / 'data'",
        'Path.home() / ".flinttrade/data/flint.duckdb"',
        'Path.home().joinpath(".flinttrade", "data")',
        'Path.home().joinpath(".flinttrade/data")',
        '"~/.flinttrade"',
        "'~/.flinttrade/data'",
        'os.path.expanduser("~/.flinttrade/sandbox/state.sqlite")',
        'f"{Path.home()}/.flinttrade"',
        'f"{Path.home()}/.flinttrade/data/{name}"',
        "Stores state in ``~/.flinttrade/engine.duckdb`` on every platform.",
        "Writes to ``~/.flinttrade`` unconditionally.",
    ],
    ids=lambda value: value[:44],
)
def test_guard_catches_every_spelling_of_the_literal(spelling: str) -> None:
    """All five forms fire; form 5 covers the reStructuredText docstring style.

    Args:
        spelling: A source fragment that must be reported.
    """
    caught = bool(_HARDCODED_WORKSPACE_RE.search(spelling)) or bool(_unqualified_doc_mentions(spelling))
    assert caught, f"the guard no longer catches {spelling!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "sibling",
    [
        'Path.home() / ".flinttrade-backups"',
        'Path.home().joinpath(".flinttrade-backups")',
        'Path.home().joinpath(".flinttrade_old", "data")',
        '"~/.flinttrade-backups"',
        "'~/.flinttrade_old/data'",
        'f"{Path.home()}/.flinttrade-backups"',
        "Rotated into ``~/.flinttrade-backups`` nightly.",
        'zipf.write(source, f".flinttrade/{name}")',
    ],
    ids=lambda value: value[:44],
)
def test_guard_ignores_unrelated_sibling_directories(sibling: str) -> None:
    """Every form ends at a separator or its closing delimiter, so siblings are not swept up.

    Forms 2-4 used to stop at the bare literal and matched ``.flinttrade-backups``
    and friends, which the comment above the pattern already (wrongly) claimed they
    did not. The last case pins the other half of that comment: an f-string archive
    name with no home anchor is not a workspace resolution.

    Args:
        sibling: A source fragment that must NOT be reported.
    """
    assert not _HARDCODED_WORKSPACE_RE.search(sibling), f"unrelated sibling swept up: {sibling!r}"
    assert not _unqualified_doc_mentions(sibling), f"unrelated sibling swept up in prose: {sibling!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "prose",
    [
        "Defaults to ``~/.flinttrade`` on Linux, ``~/Library/Application Support/flinttrade``\n"
        "on macOS and ``%APPDATA%/flinttrade`` on Windows.",
        "A pre-workspace ``~/.flinttrade/flows`` tree is copied into the workspace once.",
        "Migrates the legacy ``~/.flinttrade/data`` store forward.",
    ],
    ids=["per-os-enumerated", "pre-workspace-marked", "legacy-marked"],
)
def test_qualified_prose_mentions_are_not_violations(prose: str) -> None:
    """Documenting the real per-OS layout, or the legacy root, is the fix — not the bug.

    Args:
        prose: A docstring paragraph that must NOT be reported.
    """
    assert not _unqualified_doc_mentions(prose), f"correct documentation reported: {prose!r}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("debt", "name"),
    [
        (_STRING_LITERAL_DEBT, "_STRING_LITERAL_DEBT"),
        (_DOC_MENTION_DEBT, "_DOC_MENTION_DEBT"),
    ],
    ids=["string-literal-debt", "doc-mention-debt"],
)
def test_form_scoped_debt_still_fails_on_the_division_form(debt: frozenset[str], name: str) -> None:
    """A listed file is excused for its own backlog only, never for the whole guard.

    Folding these sets into ``_EXCUSED`` skipped the listed files entirely, so
    coverage they already had — the division form, which every one of them was clean
    of — silently regressed. Adding ``Path.home() / ".flinttrade"`` to any of them
    must still fail.

    Args:
        debt: The form-scoped debt set under test.
        name: Its identifier, for the failure message.
    """
    assert debt, f"{name} is empty; drop this test with the set"
    for rel in sorted(debt):
        assert rel not in _EXCUSED, f"{name} entry {rel} is fully excused — it must stay guarded"
        regressed = 'BASE = Path.home() / ".flinttrade" / "data"\n'
        assert _violations_in(rel, regressed), (
            f"{name} entry {rel} would not be caught adding the division form"
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
